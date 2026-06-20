# ─────────────────────────────────────────────────────────────
# FILE: app/routers/reconciliation.py
# PURPOSE: Manual trigger endpoint for reconciliation. The
#          automatic scheduled version runs via APScheduler
#          (wired in app/main.py) every 15 minutes; this endpoint
#          lets you trigger the same logic on-demand, instantly.
# ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.reconciliation import run_reconciliation

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])


@router.post("/trigger")
def trigger_reconciliation(db: Session = Depends(get_db)):
    """Manually triggers a reconciliation run immediately, instead of waiting for the schedule."""
    return run_reconciliation(db)