# ─────────────────────────────────────────────────────────────
# FILE: app/gateways/stripe_mock.py
# PURPOSE: Simulates Stripe. Same pattern as Razorpay mock —
#          see that file for detailed comments on the approach.
# ─────────────────────────────────────────────────────────────

import time
import uuid
from app.gateways.base import PaymentGateway, GatewayResponse


class StripeMockGateway(PaymentGateway):
    name = "stripe"

    def _simulate_response_type(self, mock_headers: dict) -> str:
        if not mock_headers:
            return "success"
        return mock_headers.get("X-Mock-Response", "success")

    def _simulate_delay(self, mock_headers: dict):
        if mock_headers and "X-Mock-Delay-Ms" in mock_headers:
            time.sleep(int(mock_headers["X-Mock-Delay-Ms"]) / 1000)

    def authorize(self, amount: int, currency: str, payment_method: str, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        response_type = self._simulate_response_type(mock_headers)

        if mock_headers and mock_headers.get("X-Mock-Gateway-Down") == "true":
            return GatewayResponse(success=False, error_code="GATEWAY_UNREACHABLE", error_message="Stripe is currently unreachable")

        if response_type == "timeout":
            time.sleep(30)
            return GatewayResponse(success=False, error_code="GATEWAY_TIMEOUT", error_message="Stripe did not respond within 30 seconds")

        if response_type == "server-error":
            return GatewayResponse(success=False, error_code="api_error", error_message="Stripe returned HTTP 502", raw_response={"status_code": 502})

        if response_type == "decline":
            # Stripe's real decline code convention
            return GatewayResponse(success=False, error_code="card_declined", error_message="Your card was declined", raw_response={"status_code": 402})

        if response_type == "rate-limit":
            return GatewayResponse(success=False, error_code="rate_limit", error_message="Stripe rate limit exceeded (100 req/sec test mode)", raw_response={"status_code": 429, "retry_after": 1})

        gateway_payment_id = f"pi_{uuid.uuid4().hex[:16]}"
        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="requires_capture",
            raw_response={"id": gateway_payment_id, "status": "requires_capture", "amount": amount, "currency": currency},
        )

    def capture(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        if self._simulate_response_type(mock_headers) == "server-error":
            return GatewayResponse(success=False, error_code="api_error", error_message="Stripe returned HTTP 502 during capture")

        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="succeeded",
            raw_response={"id": gateway_payment_id, "status": "succeeded", "amount": amount},
        )

    def refund(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        refund_id = f"re_{uuid.uuid4().hex[:16]}"
        return GatewayResponse(
            success=True,
            gateway_payment_id=refund_id,
            status="succeeded",
            raw_response={"id": refund_id, "payment_intent": gateway_payment_id, "amount": amount},
        )

    def get_status(self, gateway_payment_id: str) -> GatewayResponse:
        return GatewayResponse(success=True, gateway_payment_id=gateway_payment_id, status="succeeded", raw_response={"id": gateway_payment_id, "status": "succeeded"})