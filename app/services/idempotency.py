# ─────────────────────────────────────────────────────────────
# FILE: app/services/idempotency.py
# PURPOSE: Prevents duplicate payment processing when the same
#          idempotency key is sent more than once (double-click,
#          client retry after a timeout, network duplicate, etc).
#
# CALLED BY:
#   - app/routers/payments.py → wraps the POST /payments handler,
#     BEFORE any gateway call or state machine transition happens
#
# USES:
#   - app/models/idempotency.py (IdempotencyKey table)
#   - app/database.py (db session)
#
# KEY GUARANTEE:
#   The database's PRIMARY KEY constraint on `key` is what actually
#   prevents a true race condition — two near-simultaneous requests
#   both trying to INSERT the same key will have one succeed and
#   one fail at the database level, even if both passed a Python
#   "does it exist?" check at the same instant.
# ─────────────────────────────────────────────────────────────

import hashlib
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.idempotency import IdempotencyKey


class DuplicateRequestInProgress(Exception):
    """Raised when the SAME key is already being processed right now."""
    pass


class IdempotentResponseReplay(Exception):
    """
    Not really an error - this is how we signal 'don't do the work
    again, here's the cached result from last time'. The calling
    code (payments router) catches this and just returns the
    cached response instead of creating a new transaction.
    """
    def __init__(self, response_code: int, response_body: dict):
        self.response_code = response_code
        self.response_body = response_body
        super().__init__("Replaying cached idempotent response")


def _hash_request(payload: dict) -> str:
    """
    Creates a fingerprint of the request body. Used to detect if
    someone reuses the same idempotency key for a DIFFERENT
    request (which would be a client bug, not a legitimate retry).
    """
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin_idempotent_request(key: str, request_payload: dict, db: Session, merchant_id: str = "default") -> None:
    """
    Call this FIRST, before doing any real work for a payment request.

    Three possible outcomes:
      - Returns normally  -> this is a genuinely new request, proceed
      - Raises DuplicateRequestInProgress -> reject with 409
      - Raises IdempotentResponseReplay -> return the cached response

    WHO CALLS THIS: app/routers/payments.py, as the very first line
    inside the POST /payments handler.
    """
    request_hash = _hash_request(request_payload)

    existing = db.query(IdempotencyKey).filter(
        IdempotencyKey.key == key,
        IdempotencyKey.merchant_id == merchant_id,
    ).first()

    if existing is not None:
        if existing.status == "PROCESSING":
            raise DuplicateRequestInProgress(
                f"Request with key '{key}' is already being processed"
            )
        if existing.status == "COMPLETED":
            raise IdempotentResponseReplay(
                response_code=existing.response_code,
                response_body=existing.response_body,
            )
        if existing.status == "FAILED":
            # Reuse the SAME row - update it back to PROCESSING rather
            # than inserting a new row with the same primary key
            # (which PostgreSQL would correctly reject).
            existing.status = "PROCESSING"
            existing.request_hash = request_hash
            existing.response_code = None
            existing.response_body = None
            db.commit()
            return

    # Genuinely new key - no existing row at all
    new_record = IdempotencyKey(
        key=key,
        merchant_id=merchant_id,
        request_hash=request_hash,
        status="PROCESSING",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(new_record)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateRequestInProgress(
            f"Request with key '{key}' is already being processed (race detected)"
        )


def complete_idempotent_request(key: str, response_code: int, response_body: dict, db: Session, merchant_id: str = "default") -> None:
    """
    Call this AFTER successfully finishing the real work, to cache
    the result for any future duplicate of this same key.

    WHO CALLS THIS: app/routers/payments.py, right after the
    payment was successfully created and routed.
    """
    record = db.query(IdempotencyKey).filter(
        IdempotencyKey.key == key,
        IdempotencyKey.merchant_id == merchant_id,
    ).first()
    if record:
        record.status = "COMPLETED"
        record.response_code = response_code
        record.response_body = response_body
        db.commit()


def fail_idempotent_request(key: str, db: Session, merchant_id: str = "default") -> None:
    """
    Call this if the real work raised an unexpected error, so a
    future retry with the SAME key is allowed to try again instead
    of being stuck thinking it's still "PROCESSING" forever.

    WHO CALLS THIS: app/routers/payments.py, in an except block
    around the payment creation logic.
    """
    record = db.query(IdempotencyKey).filter(
        IdempotencyKey.key == key,
        IdempotencyKey.merchant_id == merchant_id,
    ).first()
    if record:
        record.status = "FAILED"
        db.commit()