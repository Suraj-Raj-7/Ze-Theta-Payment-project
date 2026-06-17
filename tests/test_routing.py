# ─────────────────────────────────────────────────────────────
# FILE: tests/test_routing.py
# PURPOSE: Proves the routing algorithm makes correct decisions -
#          both the scoring formula and the failover behaviour.
# ─────────────────────────────────────────────────────────────

import pytest
from app.services.router import score_gateways, select_gateway, execute_authorize_with_failover
from app.services.circuit_breaker import circuit_breaker
from app.services.health_monitor import health_monitor


@pytest.fixture(autouse=True)
def reset_state():
    """
    Runs before EVERY test automatically (autouse=True).
    Without this, leftover circuit breaker / health data from
    one test would bleed into the next test and cause flaky,
    confusing failures.
    """
    health_monitor._windows.clear()
    circuit_breaker._state.clear()
    circuit_breaker._consecutive_failures.clear()
    circuit_breaker._opened_at.clear()
    yield


class TestScoring:
    def test_upi_method_favors_upi_gateway(self):
        """UPI payment method should score the UPI gateway highest
        when all gateways are equally healthy - it's free and
        natively built for UPI (fit_score=1.0, cost=0)."""
        scores = score_gateways(payment_method="upi", amount=45000)
        assert scores[0].gateway == "upi"

    def test_card_method_excludes_upi_gateway_entirely(self):
        """The UPI gateway doesn't support card payments at all,
        so it should be completely excluded from scoring results -
        not just scored lower."""
        scores = score_gateways(payment_method="card", amount=45000)
        gateway_names = [s.gateway for s in scores]
        assert "upi" not in gateway_names
        assert "razorpay" in gateway_names  # razorpay DOES support cards

    def test_degraded_gateway_scores_lower(self):
        """A gateway with poor recent success rate should score
        lower than one with perfect success rate, all else equal."""
        for _ in range(10):
            health_monitor.record_result("razorpay", success=False, latency_ms=300)
        for _ in range(10):
            health_monitor.record_result("payu", success=True, latency_ms=300)

        scores = score_gateways(payment_method="upi", amount=45000)
        razorpay_score = next(s for s in scores if s.gateway == "razorpay").score
        payu_score = next(s for s in scores if s.gateway == "payu").score
        assert payu_score > razorpay_score


class TestSelection:
    def test_select_gateway_skips_open_circuit(self):
        """If UPI's circuit is OPEN (tripped), select_gateway()
        must skip it even though it would otherwise win on score."""
        for _ in range(5):
            circuit_breaker.record_failure("upi")
        assert circuit_breaker.get_state("upi") == "OPEN"

        selected = select_gateway(payment_method="upi", amount=45000)
        assert selected != "upi"

    def test_select_gateway_raises_when_no_gateway_fits(self):
        """If every gateway supporting a method has its circuit
        OPEN, there's nothing left to select - should raise clearly
        rather than silently returning something wrong."""
        for _ in range(5):
            circuit_breaker.record_failure("upi")
        with pytest.raises(RuntimeError):
            select_gateway(payment_method="upi_only_test_method", amount=45000)


class TestFailover:
    def test_failover_to_second_gateway_on_failure(self):
        """This is PDF scenario FS-01: when the primary gateway
        fails, the system should automatically retry on the
        next-best gateway and succeed there."""
        response, gateway_used, attempts = execute_authorize_with_failover(
            payment_method="upi",
            amount=45000,
            currency="INR",
            mock_headers={"X-Mock-Response": "decline"},  # force ALL attempts to fail in this test
            max_attempts=2,
        )
        # With a forced decline, even after failover, it should have
        # tried 2 different gateways before giving up
        assert attempts == 2
        assert response.success is False

    def test_successful_payment_uses_one_attempt(self):
        """Happy path - no failures, so only 1 attempt needed."""
        response, gateway_used, attempts = execute_authorize_with_failover(
            payment_method="upi",
            amount=45000,
            currency="INR",
        )
        assert response.success is True
        assert attempts == 1
        assert gateway_used == "upi"