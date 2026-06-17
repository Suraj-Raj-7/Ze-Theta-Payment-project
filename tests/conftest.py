# ─────────────────────────────────────────────────────────────
# FILE: tests/conftest.py
# PURPOSE: Pytest automatically loads this file before running
#          ANY test. We import all models here once, so every
#          test file automatically has all models registered
#          with SQLAlchemy — no need to repeat imports everywhere.
#
# WHY THIS FIXES THE 'Refund' ERROR:
#   Transaction.py has relationship("Refund", ...) — a STRING.
#   SQLAlchemy only resolves that string to the real Refund class
#   if Refund has been imported into Python's memory somewhere.
#   This file guarantees that happens before any test runs.
# ─────────────────────────────────────────────────────────────

from app.models.transaction import Transaction
from app.models.state_log import TransactionStateLog
from app.models.refund import Refund
from app.models.gateway import GatewayConfig, GatewayHealthMetric
from app.models.idempotency import IdempotencyKey
from app.models.webhook import WebhookEvent, ProcessedWebhookEvent