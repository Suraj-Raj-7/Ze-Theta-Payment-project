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
    __tablename__ = "idempotency_keys"

    # Composite primary key: (merchant_id, key) together must be
    # unique, NOT key alone. This is what actually allows two
    # different merchants to use the same key string independently
    # (PDF FS-13 requirement) - the application logic alone can't
    # provide this guarantee if the schema doesn't enforce it too.
    key = Column(String(255), primary_key=True)
    merchant_id = Column(String(255), primary_key=True, default="default")
    request_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="PROCESSING")
    response_code = Column(Integer, nullable=True)
    response_body = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<IdempotencyKey {self.merchant_id}:{self.key} status={self.status}>"
    