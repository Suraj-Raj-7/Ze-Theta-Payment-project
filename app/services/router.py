# ─────────────────────────────────────────────────────────────
# FILE: app/services/router.py
# PURPOSE: The "brain" of the system. Combines health monitor +
#          circuit breaker + gateway cost data into one weighted
#          score per gateway, picks the best one, and handles
#          automatic failover if the chosen gateway fails.
#
# CALLED BY:
#   - app/routers/payments.py → POST /payments calls this to
#     decide which gateway to use for a new payment
#
# USES:
#   - app/services/health_monitor.py → success rate, latency
#   - app/services/circuit_breaker.py → skip unhealthy gateways
#   - app/services/state_machine.py → moves transaction through
#     ROUTE_SELECTED -> AUTH_INITIATED -> AUTHORISED/AUTH_FAILED
#   - app/gateways/*.py → the actual mock gateway calls
# ─────────────────────────────────────────────────────────────

import time
from dataclasses import dataclass
from app.services.health_monitor import health_monitor
from app.services.circuit_breaker import circuit_breaker
from app.gateways.razorpay_mock import RazorpayMockGateway
from app.gateways.stripe_mock import StripeMockGateway
from app.gateways.payu_mock import PayUMockGateway
from app.gateways.upi_mock import UPIMockGateway


# Static cost data (PDF section A3.4 / A1.3) - in production this
# would live in the gateway_configs table (we'll seed that in Step 3.4)
GATEWAY_COST = {
    "razorpay": {"percentage": 2.0, "fixed_paise": 200},
    "stripe":   {"percentage": 2.5, "fixed_paise": 300},
    "payu":     {"percentage": 1.8, "fixed_paise": 150},
    "upi":      {"percentage": 0.0, "fixed_paise": 0},
}

# Which gateway supports which payment method (PDF A1.3 + A3.1 "fit score")
GATEWAY_METHOD_SUPPORT = {
    "razorpay": {"upi", "card", "netbanking"},
    "stripe":   {"card"},
    "payu":     {"upi", "card", "netbanking"},
    "upi":      {"upi"},
}

# Default weights from PDF section A3.1 - stored here as constants
# for now; Step 3.4 / later phases could move these to routing_config table
WEIGHTS = {
    "success_rate": 0.35,
    "latency": 0.20,
    "cost": 0.20,
    "health": 0.15,
    "fit": 0.10,
}

GATEWAY_INSTANCES = {
    "razorpay": RazorpayMockGateway(),
    "stripe": StripeMockGateway(),
    "payu": PayUMockGateway(),
    "upi": UPIMockGateway(),
}


@dataclass
class GatewayScore:
    gateway: str
    score: float
    success_rate: float
    p95_latency_ms: float
    circuit_state: str


def _calculate_cost_score(gateway: str, amount: int) -> float:
    """Total cost for this gateway at this amount - lower is better."""
    cfg = GATEWAY_COST[gateway]
    return (amount * cfg["percentage"] / 100) + cfg["fixed_paise"]


def _calculate_fit_score(gateway: str, payment_method: str) -> float:
    """1.0 if gateway supports this payment method, else 0.0 (PDF A3.1)."""
    return 1.0 if payment_method in GATEWAY_METHOD_SUPPORT[gateway] else 0.0


def score_gateways(payment_method: str, amount: int) -> list[GatewayScore]:
    health_data = {gw: health_monitor.get_health(gw) for gw in GATEWAY_INSTANCES}
    costs = {gw: _calculate_cost_score(gw, amount) for gw in GATEWAY_INSTANCES}

    latencies = [h.p95_latency_ms for h in health_data.values()]
    min_latency, max_latency = min(latencies), max(latencies)
    latency_range = max(max_latency - min_latency, 1)

    cost_values = list(costs.values())
    min_cost, max_cost = min(cost_values), max(cost_values)
    cost_range = max(max_cost - min_cost, 1)

    results = []
    for gateway in GATEWAY_INSTANCES:
        # HARD FILTER: a gateway that doesn't support this payment
        # method at all should never be scored as a candidate -
        # no amount of cost/speed advantage should let it "win".
        if payment_method not in GATEWAY_METHOD_SUPPORT.get(gateway, set()):
            continue

        health = health_data[gateway]
        normalized_latency = (health.p95_latency_ms - min_latency) / latency_range
        normalized_cost = (costs[gateway] - min_cost) / cost_range
        circuit_state = circuit_breaker.get_state(gateway)
        health_score = {"CLOSED": 1.0, "HALF_OPEN": 0.5, "OPEN": 0.0}[circuit_state]
        fit_score = 1.0  # already filtered above, so this is always 1.0 now

        score = (
            WEIGHTS["success_rate"] * health.success_rate +
            WEIGHTS["latency"] * (1 - normalized_latency) +
            WEIGHTS["cost"] * (1 - normalized_cost) +
            WEIGHTS["health"] * health_score +
            WEIGHTS["fit"] * fit_score
        )

        results.append(GatewayScore(
            gateway=gateway,
            score=score,
            success_rate=health.success_rate,
            p95_latency_ms=health.p95_latency_ms,
            circuit_state=circuit_state,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def select_gateway(payment_method: str, amount: int) -> str:
    """
    Returns the NAME of the best gateway to use, skipping any
    whose circuit breaker is OPEN (can_attempt() == False) and
    any with fit_score 0 (doesn't support this payment method).

    WHO CALLS THIS: app/routers/payments.py, when initiating a
    new payment, to decide which gateway to attempt first.
    """
    scored = score_gateways(payment_method, amount)

    for candidate in scored:
        if not circuit_breaker.can_attempt(candidate.gateway):
            continue  # circuit OPEN - skip, don't even try
        if candidate.gateway not in GATEWAY_METHOD_SUPPORT or payment_method not in GATEWAY_METHOD_SUPPORT[candidate.gateway]:
            continue  # doesn't support this payment method at all
        return candidate.gateway

    raise RuntimeError(f"No available gateway supports payment method: {payment_method}")


def execute_authorize_with_failover(payment_method: str, amount: int, currency: str, mock_headers: dict = None, max_attempts: int = 3) -> tuple:
    """
    THE FULL FAILOVER FLOW (PDF FS-01 scenario):
    1. Pick the best gateway
    2. Try it, timing how long it takes
    3. Record the result in health_monitor + circuit_breaker
    4. If it failed, pick the NEXT best gateway and retry
    5. Stop after max_attempts (default 3) to avoid infinite loops

    Returns: (GatewayResponse, gateway_name_used, attempt_count)

    WHO CALLS THIS: app/routers/payments.py POST /payments endpoint
    """
    attempted_gateways = set()

    for attempt in range(1, max_attempts + 1):
        scored = score_gateways(payment_method, amount)
        gateway_name = None

        for candidate in scored:
            if candidate.gateway in attempted_gateways:
                continue
            if not circuit_breaker.can_attempt(candidate.gateway):
                continue
            if payment_method not in GATEWAY_METHOD_SUPPORT.get(candidate.gateway, set()):
                continue
            gateway_name = candidate.gateway
            break

        if gateway_name is None:
            break  # no more gateways left to try

        attempted_gateways.add(gateway_name)
        gateway = GATEWAY_INSTANCES[gateway_name]

        start = time.time()
        response = gateway.authorize(amount=amount, currency=currency, payment_method=payment_method, mock_headers=mock_headers)
        latency_ms = (time.time() - start) * 1000

        health_monitor.record_result(gateway_name, success=response.success, latency_ms=latency_ms)
        if response.success:
            circuit_breaker.record_success(gateway_name)
            return response, gateway_name, attempt
        else:
            circuit_breaker.record_failure(gateway_name)
            # loop continues - will pick next-best gateway on retry

    return response, gateway_name, attempt  # last attempt's result (all failed)