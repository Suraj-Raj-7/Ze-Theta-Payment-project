# ─────────────────────────────────────────────────────────────
# FILE: app/routers/analytics.py
# PURPOSE: Basic transaction analytics. Expanded further once
#          reconciliation (Phase 6) provides richer settlement data.
# ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.transaction import Transaction, TransactionStatus

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/success-rate")
def success_rate(db: Session = Depends(get_db)):
    """Overall success rate across all transactions ever created."""
    total = db.query(func.count(Transaction.id)).scalar()
    captured = db.query(func.count(Transaction.id)).filter(
        Transaction.status.in_([TransactionStatus.CAPTURED, TransactionStatus.SETTLED])
    ).scalar()
    rate = (captured / total) if total else 0
    return {"total_transactions": total, "captured": captured, "success_rate": round(rate, 4)}


@router.get("/volume")
def volume_by_gateway(db: Session = Depends(get_db)):
    """Transaction count grouped by which gateway handled them."""
    rows = db.query(Transaction.gateway, func.count(Transaction.id)).group_by(Transaction.gateway).all()
    return [{"gateway": g or "unassigned", "count": c} for g, c in rows]