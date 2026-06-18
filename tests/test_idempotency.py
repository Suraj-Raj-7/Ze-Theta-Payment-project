# ─────────────────────────────────────────────────────────────
# FILE: tests/test_idempotency.py
# PURPOSE: Proves duplicate payment requests are handled safely -
#          this is PDF scenario FS-03 (double submit) and FS-09
#          (concurrent race condition) and FS-13 (multi-tenant key
#          collision).
# ─────────────────────────────────────────────────────────────

import pytest
from app.database import SessionLocal
from app.models.idempotency import IdempotencyKey
from app.services.idempotency import (
    begin_idempotent_request,
    complete_idempotent_request,
    fail_idempotent_request,
    DuplicateRequestInProgress,
    IdempotentResponseReplay,
)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    # Clean up any test keys so tests don't interfere with each other
    session.query(IdempotencyKey).filter(IdempotencyKey.key.like("test-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


class TestIdempotency:
    def test_new_key_proceeds_without_error(self, db):
        # Should not raise anything - this is a genuinely new request
        begin_idempotent_request("test-new-1", {"amount": 100}, db)

    def test_duplicate_while_processing_is_rejected(self, db):
        """FS-03: double submit by customer, second request must be rejected."""
        begin_idempotent_request("test-dup-1", {"amount": 100}, db)
        # Second call with the SAME key, before the first ever completes
        with pytest.raises(DuplicateRequestInProgress):
            begin_idempotent_request("test-dup-1", {"amount": 100}, db)

    def test_duplicate_after_completion_replays_cached_response(self, db):
        begin_idempotent_request("test-replay-1", {"amount": 100}, db)
        complete_idempotent_request("test-replay-1", 200, {"result": "ok"}, db)

        with pytest.raises(IdempotentResponseReplay) as exc_info:
            begin_idempotent_request("test-replay-1", {"amount": 100}, db)
        assert exc_info.value.response_body == {"result": "ok"}
        assert exc_info.value.response_code == 200

    def test_failed_request_allows_retry(self, db):
        """If the original attempt errored out, a retry with the same
        key should be allowed to actually try again - not stuck
        replaying a failure forever."""
        begin_idempotent_request("test-retry-1", {"amount": 100}, db)
        fail_idempotent_request("test-retry-1", db)

        # Should NOT raise - a fresh attempt is allowed after FAILED
        begin_idempotent_request("test-retry-1", {"amount": 100}, db)

    def test_same_key_different_merchants_are_independent(self, db):
        """FS-13: two different merchants accidentally using the same
        key string must be treated as completely separate requests."""
        begin_idempotent_request("test-shared-key", {"amount": 100}, db, merchant_id="merchant_a")
        #