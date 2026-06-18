# ─────────────────────────────────────────────────────────────
# FILE: tests/test_webhooks.py
# PURPOSE: Proves the webhook pipeline handles signature
#          verification, deduplication, and state transitions
#          correctly. Maps to PDF scenarios FS-02, FS-06, FS-10.
# ─────────────────────────────────────────────────────────────

import hmac
import hashlib
import json
import pytest
from app.database import SessionLocal
from app.models.transaction import Transaction, TransactionStatus, PaymentMethod
from app.models.webhook import ProcessedWebhookEvent
from app.services.webhook_processor import (
    process_webhook,
    verify_signature,
    InvalidWebhookSignature,
)
from app.config import settings


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.query(ProcessedWebhookEvent).filter(
        ProcessedWebhookEvent.event_id.like("test-evt-%")
    ).delete(synchronize_session=False)
    session.query(Transaction).filter(
        Transaction.merchant_order_id.like("WEBHOOK_TEST_%")
    ).delete(synchronize_session=False)
    session.commit()
    session.close()


def make_signed_payload(payload: dict, secret: str):
    raw_body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return raw_body, signature


class TestSignatureVerification:
    def test_valid_signature_passes(self):
        secret = settings.RAZORPAY_WEBHOOK_SECRET
        body, sig = make_signed_payload({"event": "test"}, secret)
        verify_signature("razorpay", body, sig)  # should not raise

    def test_tampered_body_is_rejected(self):
        """FS-10: webhook replay attack with a modified amount."""
        secret = settings.RAZORPAY_WEBHOOK_SECRET
        body, sig = make_signed_payload({"amount": 100}, secret)
        tampered_body = json.dumps({"amount": 999999}).encode()
        with pytest.raises(InvalidWebhookSignature):
            verify_signature("razorpay", tampered_body, sig)

    def test_wrong_secret_is_rejected(self):
        body, sig = make_signed_payload({"event": "test"}, "wrong-secret")
        with pytest.raises(InvalidWebhookSignature):
            verify_signature("razorpay", body, sig)


class TestWebhookProcessing:
    def test_full_pipeline_applies_valid_transition(self, db):
        txn = Transaction(
            merchant_order_id="WEBHOOK_TEST_FULL",
            amount=10000,
            payment_method=PaymentMethod.UPI,
            status=TransactionStatus.CAPTURE_INITIATED,
            gateway_payment_id="pay_full_test",
        )
        db.add(txn)
        db.commit()

        payload = {"event": "payment.captured", "gateway_payment_id": "pay_full_test"}
        body, sig = make_signed_payload(payload, settings.RAZORPAY_WEBHOOK_SECRET)

        result = process_webhook("razorpay", "test-evt-full", "payment.captured", payload, body, sig, db)
        assert result["status"] == "processed"
        assert txn.status == TransactionStatus.CAPTURED

    def test_duplicate_webhook_is_ignored(self, db):
        """FS-02: gateway sends the same webhook multiple times."""
        txn = Transaction(
            merchant_order_id="WEBHOOK_TEST_DUP",
            amount=10000,
            payment_method=PaymentMethod.UPI,
            status=TransactionStatus.CAPTURE_INITIATED,
            gateway_payment_id="pay_dup_test",
        )
        db.add(txn)
        db.commit()

        payload = {"event": "payment.captured", "gateway_payment_id": "pay_dup_test"}
        body, sig = make_signed_payload(payload, settings.RAZORPAY_WEBHOOK_SECRET)

        result1 = process_webhook("razorpay", "test-evt-dup", "payment.captured", payload, body, sig, db)
        result2 = process_webhook("razorpay", "test-evt-dup", "payment.captured", payload, body, sig, db)

        assert result1["status"] == "processed"
        assert result2["status"] == "duplicate_ignored"

    def test_forged_signature_is_rejected_before_any_processing(self, db):
        payload = {"event": "payment.captured", "gateway_payment_id": "pay_forged"}
        body = json.dumps(payload).encode()
        fake_signature = "0" * 64  # garbage signature

        with pytest.raises(InvalidWebhookSignature):
            process_webhook("razorpay", "test-evt-forged", "payment.captured", payload, body, fake_signature, db)

    def test_invalid_transition_handled_gracefully(self, db):
        """FS-06 variant: webhook arrives but transaction is in a
        state that can't validly move to CAPTURED - should not crash,
        just report the rejection."""
        txn = Transaction(
            merchant_order_id="WEBHOOK_TEST_INVALID",
            amount=10000,
            payment_method=PaymentMethod.UPI,
            status=TransactionStatus.CREATED,  # too early - no AUTHORISED/CAPTURE_INITIATED yet
            gateway_payment_id="pay_invalid_test",
        )
        db.add(txn)
        db.commit()

        payload = {"event": "payment.captured", "gateway_payment_id": "pay_invalid_test"}
        body, sig = make_signed_payload(payload, settings.RAZORPAY_WEBHOOK_SECRET)

        result = process_webhook("razorpay", "test-evt-invalid", "payment.captured", payload, body, sig, db)
        assert result["status"] == "transition_rejected"
        assert txn.status == TransactionStatus.CREATED  # unchanged