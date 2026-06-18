# ─────────────────────────────────────────────────────────────
# FILE: app/services/webhook_processor.py
# PURPOSE: Verifies webhook signatures (proves a webhook genuinely
#          came from the claimed gateway, not an attacker), then
#          deduplicates and processes incoming webhook events.
#
# CALLED BY:
#   - app/routers/webhooks.py → POST /webhooks/razorpay, /stripe,
#     /payu, /upi all call verify_signature() FIRST, before
#     anything else happens with the request
#
# USES:
#   - app/config.py (the shared webhook secrets per gateway)
#   - app/models/webhook.py (WebhookEvent, ProcessedWebhookEvent)
#   - app/services/state_machine.py (Phase 4 Step 4.3, applies
#     the actual state transition once a webhook is verified)
# ─────────────────────────────────────────────────────────────

import hmac
import hashlib
import json
from app.config import settings


GATEWAY_SECRETS = {
    "razorpay": settings.RAZORPAY_WEBHOOK_SECRET,
    "stripe": settings.STRIPE_WEBHOOK_SECRET,
    "payu": settings.PAYU_WEBHOOK_SECRET,
    "upi": settings.UPI_WEBHOOK_SECRET,
}


class InvalidWebhookSignature(Exception):
    """Raised when a webhook's signature doesn't match - it may be
    forged, tampered with, or simply misconfigured."""
    pass


def verify_signature(gateway: str, raw_body: bytes, received_signature: str) -> None:
    """
    Recomputes the expected signature from the raw request body and
    our shared secret, then compares it to what the gateway claims
    to have sent. Raises if they don't match.

    WHY raw_body AND NOT A PARSED DICT:
    The signature is computed over the EXACT bytes that were sent.
    If we parse to a dict and re-serialize it, whitespace or key
    ordering could differ, producing a different signature even for
    genuinely unmodified data. Always verify against the raw bytes.

    WHO CALLS THIS: app/routers/webhooks.py, as the very first
    thing done with any incoming webhook request, before even
    looking at what event type it claims to be.
    """
    secret = GATEWAY_SECRETS.get(gateway)
    if secret is None:
        raise InvalidWebhookSignature(f"Unknown gateway: {gateway}")

    expected_signature = hmac.new(
        key=secret.encode(),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # CRITICAL: compare_digest runs in constant time, regardless of
    # WHERE the mismatch occurs. A plain `==` comparison would leak
    # timing information an attacker could exploit (PDF A5.3).
    is_valid = hmac.compare_digest(expected_signature, received_signature)

    if not is_valid:
        raise InvalidWebhookSignature(
            f"Signature verification failed for {gateway} webhook"
        )
        
        
import hashlib as _hashlib  # already imported above as hashlib, alias avoided by reusing it
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.webhook import ProcessedWebhookEvent
from app.models.transaction import Transaction, TransactionStatus
from app.services.state_machine import TransactionStateMachine, InvalidStateTransitionException


# Maps a gateway's own event-type string to the state our state
# machine should transition the matching transaction TO.
# This is the translation layer between "gateway language" and
# "our internal state machine language".
EVENT_TO_STATE = {
    ("razorpay", "payment.authorized"): TransactionStatus.AUTHORISED,
    ("razorpay", "payment.captured"): TransactionStatus.CAPTURED,
    ("razorpay", "payment.failed"): TransactionStatus.AUTH_FAILED,
    ("stripe", "payment_intent.succeeded"): TransactionStatus.CAPTURED,
    ("stripe", "payment_intent.payment_failed"): TransactionStatus.AUTH_FAILED,
    ("payu", "success"): TransactionStatus.CAPTURED,
    ("payu", "failure"): TransactionStatus.AUTH_FAILED,
    ("upi", "SUCCESS"): TransactionStatus.CAPTURED,
    ("upi", "FAILED"): TransactionStatus.AUTH_FAILED,
}


def is_duplicate_event(gateway: str, event_id: str, db: Session) -> bool:
    """
    Checks if we've already processed this exact event before.

    WHO CALLS THIS: process_webhook() below, right after signature
    verification passes.
    """
    existing = db.query(ProcessedWebhookEvent).filter(
        ProcessedWebhookEvent.gateway == gateway,
        ProcessedWebhookEvent.event_id == event_id,
    ).first()
    return existing is not None


def process_webhook(
    gateway: str,
    event_id: str,
    event_type: str,
    payload: dict,
    raw_body: bytes,
    signature: str,
    db: Session,
) -> dict:
    """
    THE FULL PIPELINE: verify -> deduplicate -> apply state transition.

    WHO CALLS THIS: app/routers/webhooks.py - this is the single
    function each of the 4 webhook endpoints (POST /webhooks/razorpay
    etc.) delegates to, after extracting gateway/event_id/payload
    from the raw HTTP request.

    Returns a dict describing what happened, for logging/response.
    """
    # Step 1: signature check (raises InvalidWebhookSignature if bad)
    verify_signature(gateway, raw_body, signature)

    # Step 2: deduplication check
    if is_duplicate_event(gateway, event_id, db):
        return {"status": "duplicate_ignored", "event_id": event_id}

    # Step 3: record this event as processed, BEFORE applying the
    # transition. If two webhook deliveries somehow race each other
    # here, the database's composite primary key (gateway, event_id)
    # will reject the second INSERT - same race-safety pattern as
    # the idempotency service.
    payload_hash = _hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    gateway_payment_id = payload.get("gateway_payment_id") or payload.get("id") or payload.get("txn_ref")

    record = ProcessedWebhookEvent(
        gateway=gateway,
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        transaction_id=None,  # filled in below once we find the transaction
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Lost a race to another in-flight delivery of the SAME event
        return {"status": "duplicate_ignored_race", "event_id": event_id}

    # Step 4: find the transaction this webhook refers to, and
    # apply the appropriate state transition
    transaction = db.query(Transaction).filter(
        Transaction.gateway_payment_id == gateway_payment_id
    ).first()

    if transaction is None:
        return {"status": "transaction_not_found", "event_id": event_id}

    target_state = EVENT_TO_STATE.get((gateway, event_type))
    if target_state is None:
        return {"status": "unhandled_event_type", "event_type": event_type}

    sm = TransactionStateMachine()
    try:
        sm.transition(
            transaction=transaction,
            to_state=target_state,
            event=f"WEBHOOK_{event_type.upper()}",
            db=db,
            gateway_reference=gateway_payment_id,
            gateway_response=payload,
            created_by="webhook_processor",
        )
        return {"status": "processed", "event_id": event_id, "new_state": target_state.value}
    except InvalidStateTransitionException as e:
        # This handles FS-06 from the PDF: webhook arrives but the
        # transaction is already past that state (e.g. a duplicate
        # "captured" webhook after we already moved to SETTLED).
        # We don't crash - we just note it and move on gracefully.
        return {"status": "transition_rejected", "event_id": event_id, "reason": str(e)}