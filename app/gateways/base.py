# ─────────────────────────────────────────────────────────────
# FILE: app/gateways/base.py
# PURPOSE: Defines the contract every gateway adapter must follow.
#          This is the "Strategy Pattern" — the router calls these
#          methods without knowing which gateway it's actually
#          talking to. All 4 gateways are interchangeable.
#
# CALLED BY:
#   - app/services/router.py (calls .authorize() on whichever
#     gateway it selects)
#   - app/routers/payments.py (calls .capture(), .refund())
#
# IMPLEMENTED BY:
#   - app/gateways/razorpay_mock.py
#   - app/gateways/stripe_mock.py
#   - app/gateways/payu_mock.py
#   - app/gateways/upi_mock.py
# ─────────────────────────────────────────────────────────────

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class GatewayResponse:
    """
    Every gateway method returns this SAME shape, regardless of
    which gateway it came from. This is what makes gateways
    interchangeable — the router doesn't need gateway-specific
    response parsing.
    """
    success: bool
    gateway_payment_id: Optional[str] = None
    status: Optional[str] = None          # gateway's own status string
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[dict] = None    # full response, for audit log


class PaymentGateway(ABC):
    """
    Abstract base class. Cannot be instantiated directly —
    Python enforces that every subclass implements all 4 methods
    below, or it will raise a TypeError at import time.
    """

    name: str = "base"  # overridden by each subclass, e.g. "razorpay"

    @abstractmethod
    def authorize(self, amount: int, currency: str, payment_method: str, mock_headers: dict = None) -> GatewayResponse:
        """
        Step 1 of payment: ask the gateway to authorize (place a
        hold on) the given amount. Does NOT move money yet.
        """
        raise NotImplementedError

    @abstractmethod
    def capture(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        """
        Step 2: actually move the money for a previously
        authorized payment.
        """
        raise NotImplementedError

    @abstractmethod
    def refund(self, gateway_payment_id: str, amount: int, mock_headers: dict = None) -> GatewayResponse:
        """Refund a previously captured payment, fully or partially."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self, gateway_payment_id: str) -> GatewayResponse:
        """
        Poll the gateway for the current status of a payment.
        Used by the reconciliation engine (Phase 6).
        """
        raise NotImplementedError