# ─────────────────────────────────────────────────────────────
# FILE: app/models/webhook.py
# PURPOSE: Two tables —
#   1. WebhookEvent: incoming webhook queue (never lose a webhook)
#   2. ProcessedWebhookEvent: deduplication store
#
# RECEIVES DATA FROM:
#   - app/routers/webhooks.py → writes to WebhookEvent when
#     gateway sends a webhook to our endpoint
#   - app/services/webhook_processor.py → updates WebhookEvent
#     status, writes to ProcessedWebhookEvent after processing
#
# SENDS DATA TO:
#   - app/services/webhook_processor.py → reads WebhookEvent
#     queue to find pending webhooks to process
#   - app/services/state_machine.py → webhook processor calls
#     state machine to update transaction state
# ─────────────────────────────────────────────────────────────

import uuid
from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base


class WebhookEvent(Base):
    """
    Incoming webhook queue. Every gateway webhook is stored here
    immediately on receipt, before any processing happens.

    Why queue it? So that if processing fails, we can retry.
    The webhook is never lost — even if our server crashes.
    """
    __tablename__ = "webhook_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Which gateway sent this webhook
    gateway = Column(String(50), nullable=False, index=True)

    # Gateway's unique ID for this event
    # Used for deduplication in ProcessedWebhookEvent
    event_id = Column(String(255), nullable=False)

    # Type of event — "payment.captured", "payment.failed" etc.
    event_type = Column(String(100), nullable=False)

    # Full webhook payload exactly as received
    payload = Column(JSONB, nullable=False)

    # Raw signature header from gateway — stored for verification
    signature = Column(Text, nullable=True)

    # Processing status
    # PENDING → being processed → COMPLETED or FAILED → DLQ
    status = Column(String(20), nullable=False, default="PENDING", index=True)

    # How many times we've tried to process this webhook
    retry_count = Column(Integer, nullable=False, default=0)

    # Max retries before moving to Dead Letter Queue
    max_retries = Column(Integer, nullable=False, default=3)

    # When to try processing again (for retry with backoff)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    # Why it failed (if it did)
    error_message = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return (
            f"<WebhookEvent {self.gateway}:{self.event_type} "
            f"status={self.status}>"
        )


class ProcessedWebhookEvent(Base):
    """
    Deduplication store. Every successfully processed webhook
    gets one row here. Before processing any webhook, we check
    this table. Found = duplicate, skip. Not found = process.

    Composite primary key (gateway + event_id) because different
    gateways may reuse the same event IDs.
    """
    __tablename__ = "processed_webhook_events"

    # Composite primary key — gateway + event_id together are unique
    gateway = Column(String(50), primary_key=True)
    event_id = Column(String(255), primary_key=True)

    event_type = Column(String(100), nullable=False)

    # SHA-256 hash of payload — detects tampered replays
    payload_hash = Column(String(64), nullable=False)

    # Which transaction this webhook updated
    transaction_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    processed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    def __repr__(self):
        return f"<ProcessedWebhook {self.gateway}:{self.event_id}>"