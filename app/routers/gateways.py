# ─────────────────────────────────────────────────────────────
# FILE: app/routers/gateways.py
# PURPOSE: Exposes gateway health and routing info for monitoring.
# ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, HTTPException
from app.services.health_monitor import health_monitor
from app.services.circuit_breaker import circuit_breaker
from app.services.router import GATEWAY_INSTANCES, score_gateways

router = APIRouter(prefix="/api/v1/gateways", tags=["gateways"])


@router.get("")
def list_gateways():
    """Lists all configured gateways with their current circuit state."""
    return [
        {"name": name, "circuit_state": circuit_breaker.get_state(name)}
        for name in GATEWAY_INSTANCES
    ]


@router.get("/{name}/health")
def get_gateway_health(name: str):
    """Current rolling success rate + latency for one gateway."""
    if name not in GATEWAY_INSTANCES:
        raise HTTPException(status_code=404, detail="Unknown gateway")
    health = health_monitor.get_health(name)
    return {
        "gateway": name,
        "success_rate": health.success_rate,
        "p95_latency_ms": health.p95_latency_ms,
        "total_requests": health.total_requests,
        "circuit_state": circuit_breaker.get_state(name),
    }


@router.get("/{name}/metrics")
def get_gateway_metrics(name: str):
    """Detailed metrics, same data as health but framed for dashboards."""
    return get_gateway_health(name)


@router.get("/routing/scores")
def get_routing_scores(payment_method: str = "upi", amount: int = 10000):
    """Shows the live weighted score for every gateway - useful for debugging routing decisions."""
    scores = score_gateways(payment_method, amount)
    return [
        {"gateway": s.gateway, "score": round(s.score, 4), "circuit_state": s.circuit_state}
        for s in scores
    ]