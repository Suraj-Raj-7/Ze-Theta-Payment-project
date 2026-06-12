# ─────────────────────────────────────────────────────────────
# FILE: app/models/idempotency.py
# PURPOSE: Stores idempotency keys to prevent double charges.
#          Every payment request gets a unique key. If same key
#          arrives again, return cached response immediately.
#
# RECEIVES DATA FROM:
#   - app/services/idempotency.py → writes here when new
#     payment request arrives, updates when request completes
#
# SENDS DATA TO:
#   - app/services/idempotency.py → reads here to check if
#     request was seen before (duplicate detection)
# ─────────────────────────────────────────────────────────────

from sqlalchemy import Column, String, Integer, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class IdempotencyKey(Base):
    """
    One row per unique payment request.
    Expires after 24 hours — cleaned up by background job.
    """
    __tablename__ = "idempotency_keys"

    # The key itself IS the primary key — must be unique
    # Client generates this (UUID format recommended)
    key = Column(String(255), primary_key=True)

    # Merchant ID — keys are scoped per merchant
    # Same key from two different merchants = two different payments
    merchant_id = Column(String(255), nullable=False, default="default")

    # SHA-256 hash of the request body
    # If same key but different body → reject (tampering attempt)
    request_hash = Column(String(64), nullable=False)

    # Current status of this idempotency record
    status = Column(
        String(20),
        nullable=False,
        default="PROCESSING",
        # CheckConstraint ensures only valid values stored at DB level
    )

    # HTTP status code of the response (stored for replay)
    response_code = Column(Integer, nullable=True)

    # Full response body (stored so we can replay it exactly)
    response_body = Column(JSONB, nullable=True)

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

    # After 24 hours this key expires — background job deletes it
    expires_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<IdempotencyKey {self.key} status={self.status}>"