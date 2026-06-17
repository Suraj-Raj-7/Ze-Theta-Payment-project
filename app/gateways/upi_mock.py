# ─────────────────────────────────────────────────────────────
# FILE: app/gateways/upi_mock.py
# PURPOSE: Simulates UPI (NPCI). Key difference from the other 3:
#          UPI is "collect flow" — instant, single callback, no
#          separate authorize+capture phases (PDF section A1.2).
#          We still implement the same 4-method interface for
#          consistency, but capture() is effectively a no-op
#          since UPI settles instantly on authorize.
# ─────────────────────────────────────────────────────────────

import time
import uuid
from app.gateways.base import PaymentGateway, GatewayResponse


class UPIMockGateway(PaymentGateway):
    name = "upi"

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
            return GatewayResponse(success=False, error_code="GATEWAY_UNREACHABLE", error_message="UPI switch is currently unreachable")

        if response_type == "timeout":
            # PDF: UPI collect window is 5 minutes (300s), not 30/45s like cards
            time.sleep(60)  # we cap simulated sleep at 60s for practical testing
            return GatewayResponse(success=False, error_code="COLLECT_EXPIRED", error_message="UPI collect request expired (5 minute window)")

        if response_type == "server-error":
            return GatewayResponse(success=False, error_code="NPCI_ERROR", error_message="UPI switch returned an error", raw_response={"status_code": 502})

        if response_type == "decline":
            return GatewayResponse(success=False, error_code="TXN_DECLINED", error_message="Customer declined the UPI collect request", raw_response={"status_code": 400})

        if response_type == "rate-limit":
            return GatewayResponse(success=False, error_code="RATE_LIMIT", error_message="UPI aggregator rate limit exceeded", raw_response={"status_code": 429, "retry_after": 1})

        # UPI is instant (T+0) - authorize IS the final settlement
        gateway_payment_id = f"upi_{uuid.uuid4().hex[:12]}"
        return GatewayResponse(
            success=True,
            gateway_payment_id=gateway_payment_id,
            status="SUCCESS",
            raw_response={"txn_ref": gateway_payment_id, "status": "SUCCESS", "amount": amount},
        )

    def capture(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        """
        UPI has no separate capture phase — money already moved
        during authorize(). This exists only to satisfy the
        PaymentGateway interface uniformly across all 4 gateways.
        """
        return GatewayResponse(success=True, gateway_payment_id=gateway_payment_id, status="SUCCESS", raw_response={"txn_ref": gateway_payment_id, "status": "SUCCESS", "amount": amount, "note": "UPI settles instantly on authorize"})

    def refund(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        self._simulate_delay(mock_headers)
        refund_id = f"upi_rfnd_{uuid.uuid4().hex[:12]}"
        return GatewayResponse(success=True, gateway_payment_id=refund_id, status="SUCCESS", raw_response={"refund_ref": refund_id, "original_txn": gateway_payment_id, "amount": amount})

    def get_status(self, gateway_payment_id: str) -> GatewayResponse:
        return GatewayResponse(success=True, gateway_payment_id=gateway_payment_id, status="SUCCESS", raw_response={"txn_ref": gateway_payment_id, "status": "SUCCESS"})