# ─────────────────────────────────────────────────────────────
# FILE: app/models/state_log.py
# PURPOSE: Immutable audit trail. Every state transition of
#          every transaction writes one row here. Never updated,
#          only inserted. Think of it as a payment's diary.
#
# RECEIVES DATA FROM:
#   - app/services/state_machine.py → writes here on every
#     transition (the only place that should write to this table)
#
# SENDS DATA TO:
#   - app/routers/payments.py → GET /payments/{id}/timeline
#     reads this to show full payment history
#   - app/services/reconciliation.py → reads to detect anomalies
# ─────────────────────────────────────────────────────────────

import uuid
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class TransactionStateLog(Base):
    """
    One row = one state transition.
    If a payment goes through 7 states, this table
    has 7 rows for that payment_id.
    """
    __tablename__ = "transaction_state_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Which transaction this log entry belongs to
    # ForeignKey means this MUST reference a real transaction id
    # ondelete="CASCADE" means if transaction is deleted,
    # all its logs are automatically deleted too
    transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # State BEFORE this transition
    from_state = Column(String(50), nullable=True)  # null for first transition

    # State AFTER this transition
    to_state = Column(String(50), nullable=False)

    # What triggered this transition
    # e.g. "GATEWAY_AUTH_SUCCESS", "WEBHOOK_RECEIVED", "TIMEOUT"
    event = Column(String(100), nullable=False)

    # Gateway's own transaction/order ID at time of transition
    gateway_reference = Column(String(255), nullable=True)

    # Full gateway response — stored as JSONB for flexibility
    # PII (card numbers etc.) must be removed before storing
    gateway_response = Column(JSONB, nullable=True)

    # Who/what triggered this transition
    # e.g. "webhook_processor", "payment_router", "reconciliation"
    created_by = Column(String(100), nullable=False, default="system")

    # Extra context — IP address, user agent etc.
    metadata_ = Column("metadata", JSONB, nullable=True)

    # Timestamp — never changes after insert
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Relationship — lets us do state_log.transaction to get
    # the parent Transaction object without a separate query
    transaction = relationship("Transaction", back_populates="state_logs")

    def __repr__(self):
        return (
            f"<StateLog {self.from_state} → {self.to_state} "
            f"({self.event})>"
        )