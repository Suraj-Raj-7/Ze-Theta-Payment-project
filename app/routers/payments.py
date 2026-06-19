# ─────────────────────────────────────────────────────────────
# FILE: app/routers/payments.py
# PURPOSE: The core payment lifecycle API. POST /payments is the
#          single endpoint that ties together idempotency, routing,
#          gateway calls, and the state machine into one real flow.
#
# USES:
#   - app/services/idempotency.py
#   - app/services/router.py (execute_authorize_with_failover)
#   - app/services/state_machine.py
#   - app/schemas.py (request/response validation)
#   - app/database.py (get_db dependency)
# ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.schemas import (
    PaymentCreateRequest, PaymentResponse,
    CaptureRequest, RefundRequest, RefundResponse,
    TimelineResponse,
)
from app.models.transaction import Transaction, TransactionStatus
from app.models.state_log import TransactionStateLog
from app.models.refund import Refund
from app.services.idempotency import (
    begin_idempotent_request, complete_idempotent_request, fail_idempotent_request,
    DuplicateRequestInProgress, IdempotentResponseReplay,
)
from app.services.router import execute_authorize_with_failover
from app.services.state_machine import TransactionStateMachine, InvalidStateTransitionException

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])
sm = TransactionStateMachine()


@router.post("", response_model=PaymentResponse, status_code=201)
def create_payment(request: PaymentCreateRequest, db: Session = Depends(get_db)):
    """
    Initiate a new payment. Handles idempotency, gateway routing,
    automatic failover, and full state machine tracking.
    """
    request_dict = request.model_dump()

    try:
        begin_idempotent_request(request.idempotency_key, request_dict, db)
    except DuplicateRequestInProgress:
        raise HTTPException(status_code=409, detail="Request already in progress")
    except IdempotentResponseReplay as replay:
        # Same key seen before and already finished - return the SAME
        # result again instead of creating a second transaction
        return replay.response_body

    try:
        # Step 1: create the transaction record - starts at CREATED
        txn = Transaction(
            merchant_order_id=request.merchant_order_id,
            amount=request.amount,
            currency=request.currency,
            payment_method=request.payment_method,
            idempotency_key=request.idempotency_key,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        # Step 2: move through the state machine toward attempting payment
        sm.transition(txn, TransactionStatus.ROUTE_SELECTED, "ROUTER_INVOKED", db)
        sm.transition(txn, TransactionStatus.AUTH_INITIATED, "GATEWAY_CALL_STARTED", db)

        # Step 3: the actual routing + gateway call + automatic failover
        gw_response, gateway_used, attempts = execute_authorize_with_failover(
            payment_method=request.payment_method,
            amount=request.amount,
            currency=request.currency,
        )
        txn.gateway = gateway_used
        txn.attempt_count = attempts

        # Step 4: apply the outcome to the state machine
        if gw_response.success:
            txn.gateway_payment_id = gw_response.gateway_payment_id
            sm.transition(
                txn, TransactionStatus.AUTHORISED, "GATEWAY_AUTH_SUCCESS", db,
                gateway_reference=gw_response.gateway_payment_id,
                gateway_response=gw_response.raw_response,
            )
        else:
            txn.failure_reason = gw_response.error_message
            txn.gateway_error_code = gw_response.error_code
            sm.transition(
                txn, TransactionStatus.AUTH_FAILED, "GATEWAY_AUTH_FAILED", db,
                gateway_response=gw_response.raw_response,
            )

        db.commit()
        db.refresh(txn)

        response = PaymentResponse.model_validate(txn).model_dump(mode="json")
        complete_idempotent_request(request.idempotency_key, 201, response, db)
        return response

    except Exception:
        fail_idempotent_request(request.idempotency_key, db)
        raise


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: UUID, db: Session = Depends(get_db)):
    """Retrieve a payment's current status by its internal ID."""
    txn = db.query(Transaction).filter(Transaction.id == payment_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Payment not found")
    return txn


@router.get("/{payment_id}/timeline", response_model=TimelineResponse)
def get_payment_timeline(payment_id: UUID, db: Session = Depends(get_db)):
    """Returns the full, ordered state transition history for a payment."""
    txn = db.query(Transaction).filter(Transaction.id == payment_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Payment not found")

    logs = db.query(TransactionStateLog).filter(
        TransactionStateLog.transaction_id == payment_id
    ).order_by(TransactionStateLog.created_at).all()

    return TimelineResponse(
        transaction_id=txn.id,
        current_status=txn.status.value,
        history=logs,
    )


@router.post("/{payment_id}/capture", response_model=PaymentResponse)
def capture_payment(payment_id: UUID, request: CaptureRequest, db: Session = Depends(get_db)):
    """Captures a previously authorised payment - moves AUTHORISED -> CAPTURED."""
    txn = db.query(Transaction).filter(Transaction.id == payment_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Payment not found")

    try:
        sm.transition(txn, TransactionStatus.CAPTURE_INITIATED, "MERCHANT_CAPTURE_TRIGGER", db)
    except InvalidStateTransitionException as e:
        raise HTTPException(status_code=409, detail=str(e))

    sm.transition(txn, TransactionStatus.CAPTURED, "CAPTURE_CONFIRMED", db)
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{payment_id}/refund", response_model=RefundResponse, status_code=201)
def refund_payment(payment_id: UUID, request: RefundRequest, db: Session = Depends(get_db)):
    """Initiates a refund (full or partial) for a captured payment."""
    txn = db.query(Transaction).filter(Transaction.id == payment_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Payment not found")

    refund_amount = request.amount or txn.amount

    try:
        sm.transition(txn, TransactionStatus.REFUND_INITIATED, "MERCHANT_REFUND_TRIGGER", db)
    except InvalidStateTransitionException as e:
        raise HTTPException(status_code=409, detail=str(e))

    refund = Refund(
        transaction_id=txn.id,
        amount=refund_amount,
        currency=txn.currency,
        status="PROCESSING",
        reason=request.reason,
    )
    db.add(refund)

    is_full_refund = refund_amount >= txn.amount
    sm.transition(
        txn,
        TransactionStatus.REFUNDED if is_full_refund else TransactionStatus.PARTIALLY_REFUNDED,
        "REFUND_PROCESSED", db,
    )
    refund.status = "COMPLETED"
    db.commit()
    db.refresh(refund)
    return refund