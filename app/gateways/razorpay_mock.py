# ─────────────────────────────────────────────────────────────
# FILE: app/gateways/razorpay_mock.py
# PURPOSE: Simulates the Razorpay payment gateway. Reads
#          mock_headers to deterministically trigger success,
#          timeout, server error, decline, or rate-limit —
#          exactly as required by the PDF's test harness (B4.3).
#
# CALLED BY:
#   - app/services/router.py (when Razorpay is the selected gateway)
#
# IMPLEMENTS:
#   - app/gateways/base.py → PaymentGateway interface
# ─────────────────────────────────────────────────────────────

import time
import uuid
from app.gateways.base import PaymentGateway, GatewayResponse


class RazorpayMockGateway(PaymentGateway):
    name = "razorpay"

    def _simulate_response_type(self, mock_headers: dict) -> str:
        """
        Reads the X-Mock-Response header to decide behaviour.
        Defaults to 'success' if no header is given — so normal
        code (not under test) just works without extra setup.
        """
        if not mock_headers:
            return "success"
        return mock_headers.get("X-Mock-Response", "success")

    def _simulate_delay(self, mock_headers: dict):
        """Reads X-Mock-Delay-Ms to simulate network latency."""
        if mock_headers and "X-Mock-Delay-Ms" in mock_headers:
            delay_ms = int(mock_headers["X-Mock-Delay-Ms"])
            time.sleep(delay_ms / 1000)

    def authorize(self, amount: int, currency: str, payment_method: str, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        response_type = self._simulate_response_type(mock_headers)

        if mock_headers and mock_headers.get("X-Mock-Gateway-Down") == "true":
            return GatewayResponse(
                success=False,
                error_code="GATEWAY_UNREACHABLE",
                error_message="Razorpay is currently unreachable",
            )

        if response_type == "timeout":
            time.sleep(30)  # simulates the 30s timeout from the PDF (A1.3)
            return GatewayResponse(
                success=False,
                error_code="GATEWAY_TIMEOUT",
                error_message="Razorpay did not respond within 30 seconds",
            )

        if response_type == "server-error":
            return GatewayResponse(
                success=False,
                error_code="SERVER_ERROR",
                error_message="Razorpay returned HTTP 502",
                raw_response={"status_code": 502},
            )

        if response_type == "decline":
            return GatewayResponse(
                success=False,
                error_code="BAD_REQUEST_ERROR",
                error_message="The card issuer has declined this transaction",
                raw_response={"status_code": 400},
            )

        if response_type == "rate-limit":
            return GatewayResponse(
                success=False,
                error_code="RATE_LIMIT_EXCEEDED",
                error_message="Razorpay rate limit exceeded (200 req/sec)",
                raw_response={"status_code": 429, "retry_after": 1},
            )

        # default: success
        gateway_payment_id = f"pay_{uuid.uuid4().hex[:14]}"
        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="authorized",
            raw_response={"id": gateway_payment_id, "status": "authorized", "amount": amount, "currency": currency},
        )

    def capture(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        response_type = self._simulate_response_type(mock_headers)

        if response_type == "server-error":
            return GatewayResponse(
                success=False,
                error_code="SERVER_ERROR",
                error_message="Razorpay returned HTTP 502 during capture",
            )

        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="captured",
            raw_response={"id": gateway_payment_id, "status": "captured", "amount": amount},
        )

    def refund(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        refund_id = f"rfnd_{uuid.uuid4().hex[:14]}"
        return GatewayResponse(
            success=True,
            gateway_payment_id=refund_id,
            status="refunded",
            raw_response={"id": refund_id, "payment_id": gateway_payment_id, "amount": amount},
        )

    def get_status(self, gateway_payment_id: str) -> GatewayResponse:
        """Used by reconciliation engine to poll status (Phase 6)."""
        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="captured",
            raw_response={"id": gateway_payment_id, "status": "captured"},
        )