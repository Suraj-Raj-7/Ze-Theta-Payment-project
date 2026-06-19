# ─────────────────────────────────────────────────────────────
# FILE: app/routers/reconciliation.py
# PURPOSE: Manual trigger + report retrieval for reconciliation.
#          The actual engine logic is built in Phase 6 - this
#          router just exposes the API surface ahead of time.
# ─────────────────────────────────────────────────────────────

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])


@router.post("/trigger")
def trigger_reconciliation():
    """Placeholder until Phase 6 implements the real reconciliation engine."""
    return {"status": "not_implemented_yet", "note": "Reconciliation engine arrives in Phase 6"}


@router.get("/reports/{run_id}")
def get_reconciliation_report(run_id: str):
    raise HTTPException(status_code=404, detail="No reconciliation runs yet - Phase 6 not implemented")