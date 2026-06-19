# ─────────────────────────────────────────────────────────────
# FILE: app/main.py
# PURPOSE: The application entry point. Creates the FastAPI app,
#          registers every router, and is what `uvicorn` actually
#          runs. After this file, the entire system is reachable
#          over real HTTP for the first time.
#
# RUN WITH: uvicorn app.main:app --reload
# ─────────────────────────────────────────────────────────────

from fastapi import FastAPI
from app.config import settings
from app.routers import payments, webhooks, gateways, analytics, reconciliation

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Payment orchestration layer with multi-gateway routing, "
                 "failover, idempotency, and webhook reconciliation.",
)

# Each router was built independently in app/routers/ - here we just
# attach them all to the main app. FastAPI automatically merges their
# URL prefixes (e.g. /api/v1/payments) and combines their Swagger docs.
app.include_router(payments.router)
app.include_router(webhooks.router)
app.include_router(gateways.router)
app.include_router(analytics.router)
app.include_router(reconciliation.router)


@app.get("/api/v1/health", tags=["health"])
def health_check():
    """
    Required by PDF section B4.1 - the test harness polls this
    endpoint to confirm the app started successfully before running
    any scenarios against it.
    """
    return {"status": "healthy", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/", tags=["health"])
def root():
    return {"message": "PayFlow Payment Orchestration Layer is running", "docs": "/docs"}
