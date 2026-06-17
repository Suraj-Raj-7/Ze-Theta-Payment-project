# ─────────────────────────────────────────────────────────────
# FILE: app/services/circuit_breaker.py
# PURPOSE: Detects a failing gateway and stops sending it traffic,
#          instead of letting every request wait through a slow
#          timeout. Implements the standard 3-state pattern:
#          CLOSED (normal) -> OPEN (tripped) -> HALF_OPEN (testing).
#
# CALLED BY:
#   - app/services/router.py → checks can_attempt() BEFORE calling
#     a gateway, and calls record_success()/record_failure() AFTER
#
# CONFIG (from PDF section A3.3):
#   - Trips OPEN after 5 consecutive failures
#   - Stays OPEN for 30 seconds before allowing a test request
# ─────────────────────────────────────────────────────────────

from datetime import datetime, timezone, timedelta
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # normal - requests flow through
    OPEN = "OPEN"             # tripped - no requests allowed
    HALF_OPEN = "HALF_OPEN"   # testing - one request allowed


class GatewayCircuitBreaker:
    """
    One instance tracks the circuit state for ALL gateways
    (each gateway has its own independent state internally).
    Shared as a singleton, same pattern as health_monitor.
    """

    FAILURE_THRESHOLD = 5          # consecutive failures to trip OPEN
    OPEN_TIMEOUT_SECONDS = 30      # how long to stay OPEN before testing

    def __init__(self):
        # Per-gateway state, all start CLOSED (trusted) by default
        self._state: dict[str, CircuitState] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._opened_at: dict[str, datetime] = {}

    def _get_state(self, gateway: str) -> CircuitState:
        return self._state.get(gateway, CircuitState.CLOSED)

    def can_attempt(self, gateway: str) -> bool:
        """
        THE KEY METHOD. Call this BEFORE attempting a gateway call.
        Returns True if we should try this gateway, False if we
        should skip it entirely (fail fast).

        WHO CALLS THIS: app/services/router.py, when scoring/
        choosing which gateway to route a payment to.
        """
        state = self._get_state(gateway)

        if state == CircuitState.CLOSED:
            return True  # normal operation, always try

        if state == CircuitState.OPEN:
            # Check if enough time has passed to try testing again
            opened_at = self._opened_at.get(gateway)
            if opened_at and datetime.now(timezone.utc) - opened_at >= timedelta(seconds=self.OPEN_TIMEOUT_SECONDS):
                # Timeout expired - move to HALF_OPEN and allow ONE test
                self._state[gateway] = CircuitState.HALF_OPEN
                return True
            return False  # still within timeout - skip this gateway

        if state == CircuitState.HALF_OPEN:
            return True  # the one test request is allowed through

        return True

    def record_success(self, gateway: str):
        """
        Call this after a gateway call SUCCEEDS.
        WHO CALLS THIS: app/services/router.py, right after a
        successful GatewayResponse from any mock gateway.
        """
        state = self._get_state(gateway)

        if state == CircuitState.HALF_OPEN:
            # The test request succeeded - fully trust this gateway again
            self._state[gateway] = CircuitState.CLOSED

        # Any success resets the consecutive failure counter
        self._consecutive_failures[gateway] = 0

    def record_failure(self, gateway: str):
        """
        Call this after a gateway call FAILS.
        WHO CALLS THIS: app/services/router.py, right after a
        failed GatewayResponse from any mock gateway.
        """
        state = self._get_state(gateway)

        if state == CircuitState.HALF_OPEN:
            # The test request failed - gateway still broken, re-open
            self._state[gateway] = CircuitState.OPEN
            self._opened_at[gateway] = datetime.now(timezone.utc)
            return

        # CLOSED state - count consecutive failures
        self._consecutive_failures[gateway] = self._consecutive_failures.get(gateway, 0) + 1

        if self._consecutive_failures[gateway] >= self.FAILURE_THRESHOLD:
            self._state[gateway] = CircuitState.OPEN
            self._opened_at[gateway] = datetime.now(timezone.utc)

    def get_state(self, gateway: str) -> str:
        """Used by router for scoring, and by API for monitoring dashboards."""
        return self._get_state(gateway).value


# Singleton instance - shared across the whole app
circuit_breaker = GatewayCircuitBreaker()