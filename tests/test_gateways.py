# ─────────────────────────────────────────────────────────────
# FILE: tests/test_gateways.py
# PURPOSE: Verifies each mock gateway correctly simulates all
#          5 response types from the PDF (B4.3): success,
#          timeout, server-error, decline, rate-limit.
# NOTE: timeout tests are skipped by default — they intentionally
#       sleep 30-60s and would make the test suite painfully slow.
#       Run them explicitly only when you need to verify timeout
#       behaviour specifically.
# ─────────────────────────────────────────────────────────────

import pytest
from app.gateways.razorpay_mock import RazorpayMockGateway
from app.gateways.stripe_mock import StripeMockGateway
from app.gateways.payu_mock import PayUMockGateway
from app.gateways.upi_mock import UPIMockGateway


GATEWAYS = [
    RazorpayMockGateway(),
    StripeMockGateway(),
    PayUMockGateway(),
    UPIMockGateway(),
]


@pytest.mark.parametrize("gateway", GATEWAYS, ids=lambda g: g.name)
class TestMockGatewayBehaviour:

    def test_default_authorize_succeeds(self, gateway):
        result = gateway.authorize(amount=45000, currency="INR", payment_method="upi")
        assert result.success is True
        assert result.gateway_payment_id is not None

    def test_forced_decline(self, gateway):
        result = gateway.authorize(
            amount=45000, currency="INR", payment_method="upi",
            mock_headers={"X-Mock-Response": "decline"},
        )
        assert result.success is False
        assert result.error_code is not None

    def test_forced_server_error(self, gateway):
        result = gateway.authorize(
            amount=45000, currency="INR", payment_method="upi",
            mock_headers={"X-Mock-Response": "server-error"},
        )
        assert result.success is False

    def test_forced_rate_limit(self, gateway):
        result = gateway.authorize(
            amount=45000, currency="INR", payment_method="upi",
            mock_headers={"X-Mock-Response": "rate-limit"},
        )
        assert result.success is False
        assert result.raw_response.get("retry_after") is not None

    def test_gateway_down(self, gateway):
        result = gateway.authorize(
            amount=45000, currency="INR", payment_method="upi",
            mock_headers={"X-Mock-Gateway-Down": "true"},
        )
        assert result.success is False
        assert result.error_code == "GATEWAY_UNREACHABLE"

    def test_capture_after_authorize(self, gateway):
        auth_result = gateway.authorize(amount=45000, currency="INR", payment_method="upi")
        capture_result = gateway.capture(gateway_payment_id=auth_result.gateway_payment_id, amount=45000)
        assert capture_result.success is True

    def test_refund(self, gateway):
        auth_result = gateway.authorize(amount=45000, currency="INR", payment_method="upi")
        refund_result = gateway.refund(gateway_payment_id=auth_result.gateway_payment_id, amount=45000)
        assert refund_result.success is True

    def test_get_status(self, gateway):
        auth_result = gateway.authorize(amount=45000, currency="INR", payment_method="upi")
        status_result = gateway.get_status(gateway_payment_id=auth_result.gateway_payment_id)
        assert status_result.success is True


@pytest.mark.slow
def test_razorpay_timeout_simulation():
    """Marked slow - run explicitly with: pytest -m slow"""
    gateway = RazorpayMockGateway()
    result = gateway.authorize(
        amount=45000, currency="INR", payment_method="upi",
        mock_headers={"X-Mock-Response": "timeout"},
    )
    assert result.success is False
    assert result.error_code == "GATEWAY_TIMEOUT"