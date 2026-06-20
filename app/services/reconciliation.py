# ─────────────────────────────────────────────────────────────
# FILE: app/services/reconciliation.py
# PURPOSE: Background safety net. Periodically finds transactions
#          that seem "stuck" (no webhook ever arrived to resolve
#          them), actively polls the gateway for their real status,
#          and corrects our records if they're wrong. Prevents the
#          PDF's Case Study C2 scenario (silent settlement leak).
#
# CALLED BY:
#   - app/main.py (Step 6.4) → schedules this to run every 15 min
#   - app/routers/reconciliation.py → manual "trigger now" endpoint
#
# USES:
#   - app/models/transaction.py
#   - app/services/state_machine.py
#   - app/gateways/*.py (the get_status() method built in Phase 2)
# ─────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.transaction import Transaction, TransactionStatus

# How long a transaction can sit in an in-progress state before
# we consider it "stale" and worth actively checking on.
# PDF default: 5 minutes (Section A5.5)
STALE_THRESHOLD_MINUTES = 5

# States that represent "waiting for a gateway to tell us what
# happened" - these are the only ones worth reconciling. A
# transaction already in CAPTURED or FAILED doesn't need this.
IN_PROGRESS_STATES = [
    TransactionStatus.AUTH_INITIATED,
    TransactionStatus.CAPTURE_INITIATED,
]


def find_stale_transactions(db: Session) -> list[Transaction]:
    """
    Returns transactions that have been sitting in an in-progress
    state for longer than STALE_THRESHOLD_MINUTES - these are the
    ones reconciliation needs to actively investigate.

    WHO CALLS THIS: run_reconciliation() below, as the first step
    of every reconciliation run.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)

    return db.query(Transaction).filter(
        Transaction.status.in_(IN_PROGRESS_STATES),
        Transaction.created_at < cutoff,
    ).all()
    
import logging
from app.services.state_machine import TransactionStateMachine, InvalidStateTransitionException
from app.gateways.razorpay_mock import RazorpayMockGateway
from app.gateways.stripe_mock import StripeMockGateway
from app.gateways.payu_mock import PayUMockGateway
from app.gateways.upi_mock import UPIMockGateway

logger = logging.getLogger("reconciliation")

GATEWAY_INSTANCES = {
    "razorpay": RazorpayMockGateway(),
    "stripe": StripeMockGateway(),
    "payu": PayUMockGateway(),
    "upi": UPIMockGateway(),
}

# Maps the gateway's reported status string back to our internal enum
GATEWAY_STATUS_TO_INTERNAL = {
    "captured": TransactionStatus.CAPTURED,
    "succeeded": TransactionStatus.CAPTURED,
    "success": TransactionStatus.CAPTURED,
    "SUCCESS": TransactionStatus.CAPTURED,
    "authorized": TransactionStatus.AUTHORISED,
    "requires_capture": TransactionStatus.AUTHORISED,
}

sm = TransactionStateMachine()


def reconcile_transaction(txn: Transaction, db: Session) -> dict:
    if not txn.gateway or txn.gateway not in GATEWAY_INSTANCES:
        return {"transaction_id": str(txn.id), "result": "no_gateway_assigned"}

    gateway = GATEWAY_INSTANCES[txn.gateway]
    gw_response = gateway.get_status(txn.gateway_payment_id)

    reported_state = GATEWAY_STATUS_TO_INTERNAL.get(gw_response.status)
    if reported_state is None:
        return {"transaction_id": str(txn.id), "result": "unrecognized_gateway_status", "raw": gw_response.status}

    original_state = txn.status  # capture BEFORE any mutation happens

    if reported_state == original_state:
        return {"transaction_id": str(txn.id), "result": "confirmed_consistent"}

    try:
        sm.transition(
            transaction=txn,
            to_state=reported_state,
            event="RECONCILIATION_OVERRIDE",
            db=db,
            gateway_reference=txn.gateway_payment_id,
            gateway_response=gw_response.raw_response,
            created_by="reconciliation_engine",
        )
        logger.warning(
            f"Reconciliation corrected transaction {txn.id}: "
            f"was {original_state}, gateway reports {reported_state}"
        )
        return {"transaction_id": str(txn.id), "result": "corrected", "previous_state": original_state.value, "new_state": reported_state.value}
    except InvalidStateTransitionException:
        logger.error(
            f"ANOMALY: transaction {txn.id} cannot reconcile - "
            f"our state {original_state} vs gateway reports {reported_state}"
        )
        return {"transaction_id": str(txn.id), "result": "anomaly_flagged", "our_state": original_state.value, "gateway_state": reported_state.value}
    
    
def run_reconciliation(db: Session) -> dict:
    """
    THE FULL RECONCILIATION RUN: find stale transactions, check
    each one against its gateway, and summarize the results.

    WHO CALLS THIS:
      - APScheduler, automatically every 15 minutes (Step 6.4)
      - app/routers/reconciliation.py → POST /reconciliation/trigger
        for manual, on-demand runs
    """
    stale_transactions = find_stale_transactions(db)

    results = {
        "checked": len(stale_transactions),
        "confirmed_consistent": 0,
        "corrected": 0,
        "anomalies": 0,
        "details": [],
    }

    for txn in stale_transactions:
        outcome = reconcile_transaction(txn, db)
        results["details"].append(outcome)

        if outcome["result"] == "confirmed_consistent":
            results["confirmed_consistent"] += 1
        elif outcome["result"] == "corrected":
            results["corrected"] += 1
        elif outcome["result"] == "anomaly_flagged":
            results["anomalies"] += 1

    logger.info(
        f"Reconciliation run complete: checked={results['checked']} "
        f"corrected={results['corrected']} anomalies={results['anomalies']}"
    )
    return results