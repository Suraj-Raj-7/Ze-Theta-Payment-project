# ─────────────────────────────────────────────────────────────
# FILE: app/models/gateway.py
# PURPOSE: Two tables —
#   1. GatewayConfig: static settings per gateway (costs, limits)
#   2. GatewayHealthMetric: per-minute performance snapshots
#
# RECEIVES DATA FROM:
#   - app/services/health_monitor.py → writes GatewayHealthMetric
#     every minute with latest success rate + latency
#   - app/routers/gateways.py → updates GatewayConfig via API
#
# SENDS DATA TO:
#   - app/services/router.py → reads both tables to score gateways
#   - app/services/circuit_breaker.py → reads health metrics
#   - app/routers/gateways.py → GET /gateways/{name}/metrics
# ─────────────────────────────────────────────────────────────

import uuid
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base


class GatewayConfig(Base):
    """
    One row per gateway (4 rows total: razorpay, stripe, payu, upi).
    Stores everything the routing algorithm needs to know about
    a gateway's cost and capabilities.
    """
    __tablename__ = "gateway_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # "razorpay", "stripe", "payu", "upi"
    name = Column(String(50), unique=True, nullable=False, index=True)

    # Is this gateway currently enabled?
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Cost as percentage — e.g. 2.0 means 2% of transaction amount
    cost_percentage = Column(Float, nullable=False, default=2.0)

    # Fixed cost per transaction in paise — e.g. 200 = ₹2
    cost_fixed_paise = Column(Integer, nullable=False, default=200)

    # Timeout in seconds before we consider gateway unresponsive
    timeout_seconds = Column(Integer, nullable=False, default=30)

    # Max requests per second this gateway allows
    rate_limit_per_second = Column(Integer, nullable=False, default=100)

    # Which payment methods this gateway supports
    # e.g. {"upi": true, "card": true, "netbanking": false}
    supported_methods = Column(JSONB, nullable=False, default=dict)

    # Settlement cycle in days — e.g. 2 means T+2
    settlement_days = Column(Integer, nullable=False, default=2)

    # Routing priority weight (higher = preferred when scores are equal)
    priority = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    def __repr__(self):
        return f"<GatewayConfig {self.name} enabled={self.is_enabled}>"


class GatewayHealthMetric(Base):
    """
    One row per gateway per minute.
    Health monitor writes here every 60 seconds.
    Router reads the latest N rows to calculate rolling averages.

    Why store per minute? So we can see patterns over time —
    e.g. Razorpay always degrades between 6-9 PM.
    """
    __tablename__ = "gateway_health_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Which gateway this metric belongs to
    gateway = Column(String(50), nullable=False, index=True)

    # Success rate in this window — 0.0 to 1.0
    # e.g. 0.985 means 98.5% of requests succeeded
    success_rate = Column(Float, nullable=False, default=1.0)

    # 95th percentile latency in milliseconds
    # P95 means 95% of requests were faster than this
    p95_latency_ms = Column(Float, nullable=False, default=300.0)

    # Average latency in milliseconds
    avg_latency_ms = Column(Float, nullable=False, default=200.0)

    # Total requests in this time window
    total_requests = Column(Integer, nullable=False, default=0)

    # Failed requests in this time window
    failed_requests = Column(Integer, nullable=False, default=0)

    # Circuit breaker state at time of recording
    # "CLOSED" = normal, "OPEN" = tripped, "HALF_OPEN" = testing
    circuit_breaker_state = Column(
        String(20),
        nullable=False,
        default="CLOSED"
    )

    # When this metric snapshot was recorded
    recorded_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    def __repr__(self):
        return (
            f"<GatewayHealthMetric {self.gateway} "
            f"success={self.success_rate:.1%} "
            f"p95={self.p95_latency_ms}ms>"
        )