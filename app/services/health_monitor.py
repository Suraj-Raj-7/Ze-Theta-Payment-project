# ─────────────────────────────────────────────────────────────
# FILE: app/services/health_monitor.py
# PURPOSE: Tracks rolling success rate and latency per gateway,
#          using an in-memory sliding window (last N requests).
#          This is what makes the router "intelligent" instead
#          of picking gateways randomly.
#
# CALLED BY:
#   - app/services/router.py        → calls record_result() after
#     every gateway call, and get_health() before choosing a gateway
#
# WRITES TO:
#   - app/models/gateway.py (GatewayHealthMetric) → periodic
#     snapshots saved here for historical analytics (Phase 6)
# ─────────────────────────────────────────────────────────────

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import statistics


# How many recent requests we remember per gateway.
# 100 is a reasonable window — recent enough to react fast,
# large enough to not be thrown off by 1-2 unlucky requests.
WINDOW_SIZE = 100


@dataclass
class HealthSnapshot:
    """What get_health() returns - a simple summary the router can use."""
    gateway: str
    success_rate: float       # 0.0 to 1.0
    p95_latency_ms: float
    avg_latency_ms: float
    total_requests: int
    failed_requests: int


class GatewayHealthMonitor:
    """
    One instance of this is shared across the whole app (see the
    singleton pattern at the bottom of this file). It holds a
    sliding window of recent results PER gateway in memory.
    """

    def __init__(self):
        # Each gateway gets its own deque (a list that's fast at
        # dropping old items). maxlen=WINDOW_SIZE means once full,
        # adding a new item automatically drops the oldest one —
        # this IS the sliding window, Python does it for us.
        self._windows: dict[str, deque] = {}

    def _get_window(self, gateway: str) -> deque:
        """Creates a fresh window the first time we see a gateway."""
        if gateway not in self._windows:
            self._windows[gateway] = deque(maxlen=WINDOW_SIZE)
        return self._windows[gateway]

    def record_result(self, gateway: str, success: bool, latency_ms: float):
        """
        Call this after EVERY gateway API call (authorize, capture,
        refund). Records one data point into that gateway's window.

        WHO CALLS THIS: app/services/router.py, right after getting
        a GatewayResponse back from any of the 4 mock gateways.
        """
        window = self._get_window(gateway)
        window.append({
            "success": success,
            "latency_ms": latency_ms,
            "recorded_at": datetime.now(timezone.utc),
        })

    def get_health(self, gateway: str) -> HealthSnapshot:
        """
        Returns a summary of recent performance for one gateway.
        If we have no data yet (brand new gateway, no calls made),
        we return optimistic defaults so a new gateway isn't
        unfairly penalized before it's had a chance.
        """
        window = self._get_window(gateway)

        if len(window) == 0:
            return HealthSnapshot(
                gateway=gateway,
                success_rate=1.0,       # assume healthy until proven otherwise
                p95_latency_ms=300.0,   # reasonable default
                avg_latency_ms=200.0,
                total_requests=0,
                failed_requests=0,
            )

        total = len(window)
        successes = sum(1 for r in window if r["success"])
        failures = total - successes
        latencies = sorted(r["latency_ms"] for r in window)

        # P95 = the latency value below which 95% of requests fall.
        # Example: 100 requests sorted by latency, P95 is the 95th one.
        p95_index = max(0, int(len(latencies) * 0.95) - 1)
        p95_latency = latencies[p95_index]

        return HealthSnapshot(
            gateway=gateway,
            success_rate=successes / total,
            p95_latency_ms=p95_latency,
            avg_latency_ms=statistics.mean(latencies),
            total_requests=total,
            failed_requests=failures,
        )

    def get_all_gateways(self) -> list[str]:
        """Returns names of all gateways we have data for."""
        return list(self._windows.keys())


# ─────────────────────────────────────────────────────────────
# SINGLETON PATTERN
# We want ONE shared health monitor across the entire app, not
# a new empty one every time someone imports this file. This
# single instance is what router.py will import and use.
# ─────────────────────────────────────────────────────────────
health_monitor = GatewayHealthMonitor()