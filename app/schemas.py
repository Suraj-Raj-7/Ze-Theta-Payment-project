# ─────────────────────────────────────────────────────────────
# FILE: app/schemas.py
# PURPOSE: Defines the public API contract - what requests must
#          look like, and what responses look like. Completely
#          separate from app/models/ (database shape). FastAPI
#          uses these for automatic validation + Swagger docs.
#
# USED BY:
#   - app/routers/payments.py, webhooks.py, gateways.py, etc.
#     (every router imports the schemas it needs)
# ─────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


# ───────── Payment creation ─────────

class PaymentCreateRequest(BaseModel):
    """What a caller must send to POST /payments."""
    merchant_order_id: str = Field(..., description="Merchant's own order reference")
    amount: int = Field(..., gt=0, description="Amount in paise, e.g. 45000 = ₹450.00")
    currency: str = Field(default="INR", max_length=10)
    payment_method: str = Field(..., description="upi, card, netbanking, or wallet")
    idempotency_key: str = Field(..., description="Client-generated unique key for this payment attempt")

    class Config:
        json_schema_extra = {
            "example": {
                "merchant_order_id": "ORDER_12345",
                "amount": 45000,
                "currency": "INR",
                "payment_method": "upi",
                "idempotency_key": "idem_a1b2c3d4",
            }
        }


class PaymentResponse(BaseModel):
    """What we return after a payment attempt - success or failure."""
    id: UUID
    merchant_order_id: str
    amount: int
    currency: str
    status: str
    gateway: Optional[str] = None
    gateway_payment_id: Optional[str] = None
    attempt_count: int
    failure_reason: Optional[str] = None
    created_at: datetime

    class Config:
        # Allows Pydantic to build this directly from a SQLAlchemy
        # Transaction object's attributes, not just plain dicts
        from_attributes = True


# ───────── Capture / Refund ─────────

class CaptureRequest(BaseModel):
    amount: Optional[int] = Field(None, gt=0, description="Omit to capture the full authorised amount")


class RefundRequest(BaseModel):
    amount: Optional[int] = Field(None, gt=0, description="Omit for a full refund")
    reason: Optional[str] = None


class RefundResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    amount: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ───────── Timeline (audit trail) ─────────

class StateLogEntry(BaseModel):
    from_state: Optional[str]
    to_state: str
    event: str
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineResponse(BaseModel):
    transaction_id: UUID
    current_status: str
    history: list[StateLogEntry]


# ───────── Standard error format (PDF section A7.2) ─────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail