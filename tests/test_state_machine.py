# ─────────────────────────────────────────────────────────────
# FILE: tests/test_state_machine.py
# PURPOSE: Proves the state machine works correctly — every valid
#          transition succeeds, every invalid one is rejected.
# RUN WITH: pytest tests/test_state_machine.py -v
# ─────────────────────────────────────────────────────────────

import pytest
from app.database import SessionLocal
from app.models.transaction import Transaction, TransactionStatus, PaymentMethod
from app.services.state_machine import (
    TransactionStateMachine,
    InvalidStateTransitionException,
)


@pytest.fixture
def db():
    """Fresh DB session for each test, closed automatically after."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sm():
    return TransactionStateMachine()


@pytest.fixture
def new_transaction(db):
    """Creates a fresh CREATED transaction for each test."""
    txn = Transaction(
        merchant_order_id="TEST_ORDER",
        amount=10000,
        payment_method=PaymentMethod.UPI,
    )
    db.add(txn)
    db.commit()
    return txn


# ───────── VALID TRANSITIONS (happy paths) ─────────

class TestValidTransitions:
    def test_created_to_route_selected(self, sm, new_transaction, db):
        sm.transition(new_transaction, TransactionStatus.ROUTE_SELECTED, "test", db)
        assert new_transaction.status == TransactionStatus.ROUTE_SELECTED

    def test_created_to_abandoned(self, sm, new_transaction, db):
        sm.transition(new_transaction, TransactionStatus.ABANDONED, "test", db)
        assert new_transaction.status == TransactionStatus.ABANDONED

    def test_full_happy_path_to_captured(self, sm, new_transaction, db):
        """Walks a transaction through the entire successful payment journey."""
        path = [
            TransactionStatus.ROUTE_SELECTED,
            TransactionStatus.AUTH_INITIATED,
            TransactionStatus.AUTHORISED,
            TransactionStatus.CAPTURE_INITIATED,
            TransactionStatus.CAPTURED,
        ]
        for next_state in path:
            sm.transition(new_transaction, next_state, "test", db)
        assert new_transaction.status == TransactionStatus.CAPTURED
        # captured_at should auto-populate — we coded this in state_machine.py
        assert new_transaction.captured_at is not None

    def test_auth_failed_allows_retry(self, sm, new_transaction, db):
        """Failover scenario: auth fails, then retries on new gateway."""
        sm.transition(new_transaction, TransactionStatus.ROUTE_SELECTED, "test", db)
        sm.transition(new_transaction, TransactionStatus.AUTH_INITIATED, "test", db)
        sm.transition(new_transaction, TransactionStatus.AUTH_FAILED, "test", db)
        # retry on a different gateway
        sm.transition(new_transaction, TransactionStatus.ROUTE_SELECTED, "test", db)
        assert new_transaction.status == TransactionStatus.ROUTE_SELECTED

    def test_captured_to_refund_initiated(self, sm, new_transaction, db):
        for s in [
            TransactionStatus.ROUTE_SELECTED,
            TransactionStatus.AUTH_INITIATED,
            TransactionStatus.AUTHORISED,
            TransactionStatus.CAPTURE_INITIATED,
            TransactionStatus.CAPTURED,
            TransactionStatus.REFUND_INITIATED,
        ]:
            sm.transition(new_transaction, s, "test", db)
        assert new_transaction.status == TransactionStatus.REFUND_INITIATED

    def test_partial_capture_then_capture_remainder(self, sm, new_transaction, db):
        for s in [
            TransactionStatus.ROUTE_SELECTED,
            TransactionStatus.AUTH_INITIATED,
            TransactionStatus.AUTHORISED,
            TransactionStatus.CAPTURE_INITIATED,
            TransactionStatus.PARTIALLY_CAPTURED,
            TransactionStatus.CAPTURE_INITIATED,  # capture the rest
            TransactionStatus.CAPTURED,
        ]:
            sm.transition(new_transaction, s, "test", db)
        assert new_transaction.status == TransactionStatus.CAPTURED


# ───────── INVALID TRANSITIONS (must be rejected) ─────────

class TestInvalidTransitions:
    def test_cannot_skip_created_to_captured(self, sm, new_transaction, db):
        """This is FS-15 from the PDF — state machine corruption attempt."""
        with pytest.raises(InvalidStateTransitionException):
            sm.transition(new_transaction, TransactionStatus.CAPTURED, "bad", db)
        # transaction must remain UNCHANGED after rejection
        assert new_transaction.status == TransactionStatus.CREATED

    def test_cannot_skip_created_to_refunded(self, sm, new_transaction, db):
        with pytest.raises(InvalidStateTransitionException):
            sm.transition(new_transaction, TransactionStatus.REFUNDED, "bad", db)
        assert new_transaction.status == TransactionStatus.CREATED

    def test_cannot_go_backwards_from_captured(self, sm, new_transaction, db):
        for s in [
            TransactionStatus.ROUTE_SELECTED,
            TransactionStatus.AUTH_INITIATED,
            TransactionStatus.AUTHORISED,
            TransactionStatus.CAPTURE_INITIATED,
            TransactionStatus.CAPTURED,
        ]:
            sm.transition(new_transaction, s, "test", db)
        # CAPTURED cannot go back to AUTH_INITIATED
        with pytest.raises(InvalidStateTransitionException):
            sm.transition(new_transaction, TransactionStatus.AUTH_INITIATED, "bad", db)

    def test_terminal_state_failed_has_no_exits(self, sm, new_transaction, db):
        sm.transition(new_transaction, TransactionStatus.ROUTE_SELECTED, "test", db)
        sm.transition(new_transaction, TransactionStatus.AUTH_INITIATED, "test", db)
        sm.transition(new_transaction, TransactionStatus.AUTH_FAILED, "test", db)
        sm.transition(new_transaction, TransactionStatus.FAILED, "test", db)
        # nothing should be allowed after FAILED
        with pytest.raises(InvalidStateTransitionException):
            sm.transition(new_transaction, TransactionStatus.ROUTE_SELECTED, "bad", db)

    def test_terminal_state_refunded_has_no_exits(self, sm, new_transaction, db):
        for s in [
            TransactionStatus.ROUTE_SELECTED,
            TransactionStatus.AUTH_INITIATED,
            TransactionStatus.AUTHORISED,
            TransactionStatus.CAPTURE_INITIATED,
            TransactionStatus.CAPTURED,
            TransactionStatus.REFUND_INITIATED,
            TransactionStatus.REFUNDED,
        ]:
            sm.transition(new_transaction, s, "test", db)
        with pytest.raises(InvalidStateTransitionException):
            sm.transition(new_transaction, TransactionStatus.CAPTURED, "bad", db)

    def test_error_message_lists_valid_options(self, sm, new_transaction, db):
        """The error must tell the developer what WAS allowed — good DX."""
        with pytest.raises(InvalidStateTransitionException) as exc_info:
            sm.transition(new_transaction, TransactionStatus.CAPTURED, "bad", db)
        assert "ROUTE_SELECTED" in str(exc_info.value)
        assert "ABANDONED" in str(exc_info.value)


# ───────── HELPER METHODS ─────────

class TestHelperMethods:
    def test_get_allowed_next_states(self, sm):
        allowed = sm.get_allowed_next_states(TransactionStatus.CREATED)
        assert TransactionStatus.ROUTE_SELECTED in allowed
        assert TransactionStatus.ABANDONED in allowed
        assert len(allowed) == 2

    def test_is_terminal_state_true_for_failed(self, sm):
        assert sm.is_terminal_state(TransactionStatus.FAILED) is True

    def test_is_terminal_state_false_for_created(self, sm):
        assert sm.is_terminal_state(TransactionStatus.CREATED) is False

    def test_is_terminal_state_true_for_refunded(self, sm):
        assert sm.is_terminal_state(TransactionStatus.REFUNDED) is True