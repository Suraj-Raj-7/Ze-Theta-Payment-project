import pytest
from datetime import datetime, timedelta, timezone
from app.database import SessionLocal
from app.models.transaction import Transaction, TransactionStatus, PaymentMethod
from app.services.reconciliation import find_stale_transactions, reconcile_transaction, run_reconciliation


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.query(Transaction).filter(Transaction.merchant_order_id.like("RECTEST_%")).delete(synchronize_session=False)
    session.commit()
    session.close()


def make_stale(db, order_id, status, gateway=None, minutes_old=10):
    txn = Transaction(merchant_order_id=order_id, amount=10000, payment_method=PaymentMethod.UPI,
                       status=status, gateway=gateway, gateway_payment_id=f"pay_{order_id}")
    db.add(txn)
    db.commit()
    db.query(Transaction).filter(Transaction.id == txn.id).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_old)})
    db.commit()
    db.refresh(txn)
    return txn


class TestReconciliation:
    def test_stale_detection_respects_threshold(self, db):
        old = make_stale(db, "RECTEST_OLD", TransactionStatus.AUTH_INITIATED, minutes_old=10)
        fresh = make_stale(db, "RECTEST_FRESH", TransactionStatus.AUTH_INITIATED, minutes_old=1)
        stale_ids = [t.id for t in find_stale_transactions(db)]
        assert old.id in stale_ids
        assert fresh.id not in stale_ids

    def test_mismatch_gets_corrected(self, db):
        txn = make_stale(db, "RECTEST_MISMATCH", TransactionStatus.CAPTURE_INITIATED, gateway="upi")
        result = reconcile_transaction(txn, db)
        assert result["result"] == "corrected"
        assert result["previous_state"] == "CAPTURE_INITIATED"
        assert txn.status == TransactionStatus.CAPTURED

    def test_no_gateway_handled_gracefully(self, db):
        txn = make_stale(db, "RECTEST_NOGW", TransactionStatus.AUTH_INITIATED, gateway=None)
        result = reconcile_transaction(txn, db)
        assert result["result"] == "no_gateway_assigned"

    def test_full_run_summarizes_correctly(self, db):
        make_stale(db, "RECTEST_RUN1", TransactionStatus.CAPTURE_INITIATED, gateway="upi")
        summary = run_reconciliation(db)
        assert summary["checked"] >= 1
        assert "details" in summary