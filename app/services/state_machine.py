# ─────────────────────────────────────────────────────────────
# FILE: app/services/state_machine.py
# PURPOSE: The brain of the payment system. Enforces which state
#          transitions are valid. Writes every transition to the
#          audit log automatically.
#
# CALLED BY:
#   - app/services/router.py        (CREATED → ROUTE_SELECTED)
#   - app/gateways/*.py              (AUTH_INITIATED → AUTHORISED/FAILED)
#   - app/services/webhook_processor.py (webhook-driven transitions)
#   - app/routers/payments.py        (capture, refund, void triggers)
#   - app/services/reconciliation.py (RECONCILIATION_OVERRIDE)
#
# WRITES TO:
#   - app/models/transaction.py      (updates .status field)
#   - app/models/state_log.py        (inserts audit trail row)
# ─────────────────────────────────────────────────────────────

from app.models.transaction import TransactionStatus


class InvalidStateTransitionException(Exception):
    """
    Raised when code tries an illegal transition,
    e.g. CREATED → REFUNDED (skipping all the steps between).
    Catching this specific exception lets calling code show
    a clear error instead of silently corrupting data.
    """
    def __init__(self, from_state, to_state, allowed_states):
        self.from_state = from_state
        self.to_state = to_state
        self.allowed_states = allowed_states
        message = (
            f"Cannot transition from '{from_state}' to '{to_state}'. "
            f"Valid next states from '{from_state}' are: "
            f"{[s.value for s in allowed_states]}"
        )
        super().__init__(message)


# ─────────────────────────────────────────────────────────────
# THE RULEBOOK
# Dictionary where each key is a state, and the value is the
# LIST of states it's allowed to move to.
# This is a direct Python translation of the table from the PDF
# (Section A2.2) and our earlier diagram.
# ─────────────────────────────────────────────────────────────

VALID_TRANSITIONS = {
    TransactionStatus.CREATED: [
        TransactionStatus.ROUTE_SELECTED,
        TransactionStatus.ABANDONED,
    ],
    TransactionStatus.ROUTE_SELECTED: [
        TransactionStatus.AUTH_INITIATED,
        TransactionStatus.ROUTE_FAILED,
    ],
    TransactionStatus.AUTH_INITIATED: [
        TransactionStatus.AUTHORISED,
        TransactionStatus.AUTH_FAILED,
        TransactionStatus.AUTH_TIMEOUT,
    ],
    TransactionStatus.AUTHORISED: [
        TransactionStatus.CAPTURE_INITIATED,
        TransactionStatus.VOID_INITIATED,
        TransactionStatus.AUTH_EXPIRED,
    ],
    TransactionStatus.AUTH_FAILED: [
        TransactionStatus.ROUTE_SELECTED,  # retry with different gateway
        TransactionStatus.FAILED,
    ],
    TransactionStatus.AUTH_TIMEOUT: [
        TransactionStatus.ROUTE_SELECTED,  # retry with different gateway
        TransactionStatus.FAILED,
    ],
    TransactionStatus.CAPTURE_INITIATED: [
        TransactionStatus.CAPTURED,
        TransactionStatus.PARTIALLY_CAPTURED,
        TransactionStatus.CAPTURE_FAILED,
    ],
    TransactionStatus.CAPTURED: [
        TransactionStatus.REFUND_INITIATED,
        TransactionStatus.SETTLED,
    ],
    TransactionStatus.PARTIALLY_CAPTURED: [
        TransactionStatus.CAPTURE_INITIATED,  # capture the remainder
        TransactionStatus.REFUND_INITIATED,
        TransactionStatus.SETTLED,
    ],
    TransactionStatus.CAPTURE_FAILED: [
        TransactionStatus.CAPTURE_INITIATED,  # retry capture
        TransactionStatus.VOID_INITIATED,
    ],
    TransactionStatus.VOID_INITIATED: [
        TransactionStatus.VOIDED,
    ],
    TransactionStatus.SETTLED: [
        TransactionStatus.REFUND_INITIATED,
        TransactionStatus.DISPUTE_OPENED,
    ],
    TransactionStatus.REFUND_INITIATED: [
        TransactionStatus.REFUNDED,
        TransactionStatus.PARTIALLY_REFUNDED,
        TransactionStatus.REFUND_FAILED,
    ],
    TransactionStatus.PARTIALLY_REFUNDED: [
        TransactionStatus.REFUND_INITIATED,  # refund more later
        TransactionStatus.SETTLED,
    ],
    TransactionStatus.REFUND_FAILED: [
        TransactionStatus.REFUND_INITIATED,  # retry refund
    ],
    TransactionStatus.DISPUTE_OPENED: [
        TransactionStatus.DISPUTE_RESOLVED,
    ],
    TransactionStatus.ROUTE_FAILED: [
        TransactionStatus.ROUTE_SELECTED,  # try again
        TransactionStatus.FAILED,
    ],

    # ─────────────────────────────────────
    # TERMINAL STATES — empty list means
    # NOTHING can come after these. Final stop.
    # ─────────────────────────────────────
    TransactionStatus.FAILED: [],
    TransactionStatus.REFUNDED: [],
    TransactionStatus.ABANDONED: [],
    TransactionStatus.VOIDED: [],
    TransactionStatus.AUTH_EXPIRED: [],
    TransactionStatus.DISPUTE_RESOLVED: [],
}


from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.transaction import Transaction
from app.models.state_log import TransactionStateLog


class TransactionStateMachine:
    """
    The single gatekeeper for all transaction state changes.
    No other code should ever do `transaction.status = X` directly —
    everything must go through this class's transition() method.
    This guarantees no invalid transition ever reaches the database.
    """

    def transition(
        self,
        transaction: Transaction,
        to_state: TransactionStatus,
        event: str,
        db: Session,
        gateway_reference: str = None,
        gateway_response: dict = None,
        created_by: str = "system",
    ) -> Transaction:
        """
        Attempts to move `transaction` to `to_state`.

        WHO CALLS THIS:
          - app/services/router.py        → to_state=ROUTE_SELECTED
          - app/gateways/*.py              → to_state=AUTHORISED / AUTH_FAILED
          - app/services/webhook_processor.py → to_state=CAPTURED etc.
          - app/routers/payments.py        → to_state=REFUND_INITIATED etc.

        WHAT IT RETURNS:
          The same transaction object, now updated, ready to be
          used by whatever code called this (e.g. to build an API response).

        RAISES:
          InvalidStateTransitionException if the move isn't allowed.
        """

        current_state = transaction.status

        # Look up what this current_state is ALLOWED to move to
        allowed_next_states = VALID_TRANSITIONS.get(current_state, [])

        # THE CORE CHECK — this single 'if' is what makes the
        # entire system safe from corrupted financial data
        if to_state not in allowed_next_states:
            raise InvalidStateTransitionException(
                from_state=current_state,
                to_state=to_state,
                allowed_states=allowed_next_states,
            )

        # ── Transition is valid — apply it ──

        # 1. Update the transaction's status in memory
        transaction.status = to_state

        # 2. Set helpful timestamp fields automatically
        #    so we don't have to remember to do this everywhere
        if to_state == TransactionStatus.CAPTURED:
            transaction.captured_at = datetime.now(timezone.utc)

        if gateway_reference:
            transaction.gateway_payment_id = gateway_reference

        # 3. Create the audit log row — this is what makes the
        #    system auditable. Every transition, no exceptions.
        log_entry = TransactionStateLog(
            transaction_id=transaction.id,
            from_state=current_state.value if current_state else None,
            to_state=to_state.value,
            event=event,
            gateway_reference=gateway_reference,
            gateway_response=gateway_response,
            created_by=created_by,
        )

        # 4. Save both changes to the database in ONE transaction.
        #    Either both succeed or both fail — never half-saved.
        db.add(transaction)
        db.add(log_entry)
        db.commit()
        db.refresh(transaction)

        return transaction

    def get_allowed_next_states(self, current_state: TransactionStatus) -> list:
        """
        Helper to check what moves are possible from a given state,
        WITHOUT actually attempting a transition.

        WHO USES THIS:
          - app/routers/payments.py → to show the user/API consumer
            what actions are currently possible on a transaction
            (e.g. "can I refund this?" before showing a refund button)
        """
        return VALID_TRANSITIONS.get(current_state, [])

    def is_terminal_state(self, state: TransactionStatus) -> bool:
        """
        Returns True if no further transitions are possible.
        WHO USES THIS:
          - app/services/reconciliation.py → skips terminal transactions,
            no need to check their status with the gateway again
        """
        return len(VALID_TRANSITIONS.get(state, [])) == 0