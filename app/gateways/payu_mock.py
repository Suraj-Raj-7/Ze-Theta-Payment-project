# ─────────────────────────────────────────────────────────────
# FILE: app/gateways/payu_mock.py
# PURPOSE: Simulates PayU. Note: PDF states PayU has "limited"
#          auth+capture support and only "best effort" retries —
#          we reflect that with a slightly higher base unreliability
#          if ever extended, but core mock behaviour matches others.
# ─────────────────────────────────────────────────────────────

import time
import uuid
from app.gateways.base import PaymentGateway, GatewayResponse


class PayUMockGateway(PaymentGateway):
    name = "payu"

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
            return GatewayResponse(success=False, error_code="GATEWAY_UNREACHABLE", error_message="PayU is currently unreachable")

        if response_type == "timeout":
            time.sleep(45)  # PDF table A1.3: PayU timeout is 45s, not 30s
            return GatewayResponse(success=False, error_code="GATEWAY_TIMEOUT", error_message="PayU did not respond within 45 seconds")

        if response_type == "server-error":
            return GatewayResponse(success=False, error_code="TXN_FAILED", error_message="PayU returned HTTP 502", raw_response={"status_code": 502})

        if response_type == "decline":
            return GatewayResponse(success=False, error_code="DECLINED", error_message="Transaction declined by issuer", raw_response={"status_code": 400})
        
        if response_type == "rate-limit":
            return GatewayResponse(success=False, error_code="RATE_LIMIT", error_message="PayU rate limit exceeded (150 req/sec)", raw_response={"status_code": 429, "retry_after": 1})

        gateway_payment_id = f"payu_{uuid.uuid4().hex[:12]}"
        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="success",
            raw_response={"txnid": gateway_payment_id, "status": "success", "amount": amount, "currency": currency},
        )

    def capture(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        if self._simulate_response_type(mock_headers) == "server-error":
            return GatewayResponse(success=False, error_code="TXN_FAILED", error_message="PayU returned HTTP 502 during capture")

        return GatewayResponse(success=True, gateway_payment_id=gateway_payment_id, status="success", raw_response={"txnid": gateway_payment_id, "status": "success", "amount": amount})

    def refund(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        refund_id = f"payu_rfnd_{uuid.uuid4().hex[:12]}"
        return GatewayResponse(success=True, gateway_payment_id=refund_id, status="success", raw_response={"refund_id": refund_id, "txnid": gateway_payment_id, "amount": amount})

    def get_status(self, gateway_payment_id: str) -> GatewayResponse:
        return GatewayResponse(success=True, gateway_payment_id=gateway_payment_id, status="success", raw_response={"txnid": gateway_payment_id, "status": "success"})