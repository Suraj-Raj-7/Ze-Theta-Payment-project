# ─────────────────────────────────────────────────────────────
# FILE: app/routers/webhooks.py
# PURPOSE: Receives async notifications from each gateway.
#          Delegates everything to webhook_processor.process_webhook().
# ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.webhook_processor import process_webhook, InvalidWebhookSignature

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


async def _handle_webhook(gateway: str, request: Request, signature_header: str, db: Session):
    raw_body = await request.body()
    payload = await request.json()
    signature = request.headers.get(signature_header, "")

    event_id = payload.get("event_id") or payload.get("id") or payload.get("txn_ref", "unknown")
    event_type = payload.get("event") or payload.get("status", "unknown")

    try:
        result = process_webhook(gateway, event_id, event_type, payload, raw_body, signature, db)
    except InvalidWebhookSignature:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    return result


@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("razorpay", request, "X-Razorpay-Signature", db)


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("stripe", request, "Stripe-Signature", db)


@router.post("/payu")
async def payu_webhook(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("payu", request, "X-PayU-Signature", db)


@router.post("/upi")
async def upi_webhook(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("upi", request, "X-UPI-Signature", db)