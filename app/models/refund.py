# ─────────────────────────────────────────────────────────────
# FILE: app/models/refund.py
# PURPOSE: Stores refund records linked to parent transactions.
#          Original transaction is never modified — refunds are
#          separate rows. Complete audit trail preserved.
#
# RECEIVES DATA FROM:
#   - app/routers/payments.py → POST /payments/{id}/refund
#     creates a new Refund row
#   - app/services/webhook_processor.py → updates refund status
#     when gateway sends refund confirmation webhook
#
# SENDS DATA TO:
#   - app/routers/payments.py → GET /payments/{id}/refunds
#     returns all refunds for a transaction
#   - app/services/reconciliation.py → checks refund amounts
#     match gateway settlement data
# ─────────────────────────────────────────────────────────────

import uuid
from sqlalchemy import Column, String, BigInteger, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Refund(Base):
    """
    One row per refund attempt. A single transaction can have
    multiple partial refunds — each is a separate row here.
    """
    __tablename__ = "refunds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Parent transaction — must exist in transactions table
    transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Refund amount in paise — can be less than transaction amount
    # e.g. transaction was ₹1200, partial refund of ₹400 = 40000 paise
    amount = Column(BigInteger, nullable=False)

    currency = Column(String(10), nullable=False, default="INR")

    # Current state of this refund
    status = Column(String(50), nullable=False, default="PENDING", index=True)

    # Gateway's ID for this refund — needed for status checks
    gateway_refund_id = Column(String(255), nullable=True)

    # Why refund was initiated — "customer_request", "fraud" etc.
    reason = Column(String(500), nullable=True)

    # Internal notes
    notes = Column(Text, nullable=True)

    # Full gateway response when refund was processed
    gateway_response = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship back to parent transaction
    transaction = relationship("Transaction", back_populates="refunds")

    def __repr__(self):
        return (
            f"<Refund {self.id} amount={self.amount} "
            f"status={self.status}>"
        )