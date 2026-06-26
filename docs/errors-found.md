# Errors Found — Real Bugs Encountered During Development

> This document records every real bug found during the build,
> how it was discovered, what caused it, and how it was fixed.
> Written as interview revision material — each entry includes
> a plain-English explanation and a ready-to-use spoken answer.

---

## Phase 4 — Bug 1: Retrying a Failed Idempotency Key Crashed With a Duplicate-Key Error

### What was being built
`app/services/idempotency.py` — the service that prevents a payment
from being charged twice if the same client key is submitted more
than once.

### How it was discovered
A test for retrying a previously failed payment:
```python
begin_idempotent_request("test-retry-1", {...}, db)
fail_idempotent_request("test-retry-1", db)
begin_idempotent_request("test-retry-1", {...}, db)  # should succeed
```
Failed with a database error, not an assertion failure:
```
psycopg2.errors.UniqueViolation: duplicate key value
violates unique constraint "idempotency_keys_pkey"
```

### Root cause
The code correctly detected the existing row had `status = FAILED`
and was meant to allow a retry. But the retry path fell through to
the same code used for a brand-new key — which always does an INSERT.
Since a row with that primary key already existed, PostgreSQL rejected
the second INSERT.

The logic correctly identified a retry should be allowed, but then
tried to create a second row with an already-used primary key.

### Fix applied
Added an explicit branch for the FAILED case that updates the existing
row in place instead of inserting a new one:

```python
if existing.status == "FAILED":
    existing.status = "PROCESSING"
    existing.request_hash = request_hash
    existing.response_code = None
    existing.response_body = None
    db.commit()
    return
```

### Why this matters
This is a common ORM bug: confusing "this row needs to change state"
with "this row needs to be created." Any time code branches on whether
a record already exists, each branch must be deliberate about whether
it's updating or inserting — falling through to the wrong path causes
exactly this kind of primary-key collision.


---

## Phase 4 — Bug 2: A Webhook "Failure" That Was Actually the System Working Correctly

### What was being built
`app/services/webhook_processor.py` — the webhook processing pipeline.

### What happened
A manual test created a transaction directly in `AUTH_INITIATED`, then
sent it a `payment.captured` webhook. The pipeline returned:
```
{'status': 'transition_rejected', 'reason':
 "Cannot transition from AUTH_INITIATED to CAPTURED."}
```
This looked like a bug at first glance.

### Diagnosis
Tracing through the state machine's rulebook showed the rejection was
entirely correct. `AUTH_INITIATED` can only move to `AUTHORISED`,
`AUTH_FAILED`, or `AUTH_TIMEOUT` — never directly to `CAPTURED`.
A real transaction would always pass through `AUTHORISED` and
`CAPTURE_INITIATED` first. The test data was unrealistic, not the
webhook logic broken.

### Resolution
Re-ran the test with the transaction starting in `CAPTURE_INITIATED`
(a valid predecessor to `CAPTURED`) and the pipeline processed it
correctly end-to-end.

### Why this matters
Not every error message means the code under test is wrong. When a
safety mechanism rejects an operation, the first question should be:
"is the rejection correct?" before assuming a defect. Reading the
error message's actual content — not just reacting to its presence —
is what separates productive debugging from chasing phantom bugs.


---

## Phase 6 — Bug 1: Reconciliation Reported the Wrong "Previous State"

### What was being built
`app/services/reconciliation.py` — the reconciliation engine that
corrects transactions whose state doesn't match what the gateway reports.

### How it was discovered
A manual test ran reconciliation on a transaction in `CAPTURE_INITIATED`.
The correction worked — the database updated to `CAPTURED`. But the
returned log message read:
```
was TransactionStatus.CAPTURED, gateway reports TransactionStatus.CAPTURED
```
Both sides showed the same value even though a correction had just happened.

### Root cause
The comparison between internal status and gateway status was performed
correctly before any change. But the log message was built using
`txn.status` read again afterward — by which point `sm.transition()`
had already mutated the same in-memory object. SQLAlchemy model
instances are mutated directly rather than returned as new copies,
so any reference to `txn.status` taken after the transition reflects
the new state, not the one that was compared.

The code correctly detected and corrected a real mismatch, but then
described the mismatch using a value already overwritten by the fix.

### Fix applied
Captured the original status into its own variable before any mutating
call:

```python
original_state = txn.status  # captured BEFORE sm.transition() can mutate it

if reported_state == original_state:
    return {"result": "confirmed_consistent"}

sm.transition(transaction=txn, to_state=reported_state, ...)

return {
    "result": "corrected",
    "previous_state": original_state.value,  # uses the captured value
    "new_state": reported_state.value
}
```

### Why this matters
This is a recognisable category of bug: reading a mutable object's
attribute after a function has changed it, when the intent was to
capture its value from before that change. It appears anywhere
"before/after" reporting is built around an object mutated in place —
audit logs, diffs, undo systems, and reconciliation are all common
places this surfaces. Fix: snapshot the value at the moment you need
it, before calling anything that might change it.


---

## Phase 6 — Discovery: Stale Test Data Surfaced by the Reconciliation Engine

### What happened
The first live test of `find_stale_transactions()` returned not only
the deliberately-created test transaction, but also a transaction named
`WEBHOOK_TEST` — left over from manual testing during Phase 4, still
sitting in `AUTH_INITIATED` from the previous day.

### Diagnosis
Not a code defect. The function's job is to find any transaction stuck
in an in-progress state past the staleness threshold. It has no way to
know whether a stuck transaction came from a deliberate test, a real
payment, or leftover debugging data — and it shouldn't, because in
production an abandoned transaction looks identical to a genuine gateway
failure.

The discovery revealed an operational fact: manual, ad-hoc terminal
scripts used throughout earlier phases don't clean up after themselves
the way pytest fixtures do. The database accumulates "ghost" records
across sessions.

### Why this matters
This is a preview of a problem that would have caused confusing failures
in Phase 7's end-to-end scenario tests, where assertions about "exactly
N transactions in this state" would be silently polluted by unrelated
leftover rows. Recognising it early, while the cause was obvious, is
the same instinct that prevents far more expensive debugging sessions
later. Every pytest fixture in this project explicitly deletes its own
test rows in teardown for exactly this reason.

---

## Phase 7 — Bug 1: A Composite Primary Key Existed in the Model But Not in the Database

### What was being built
A test for FS-13 (idempotency key collision across merchants) verifying
that two different merchants using the same idempotency key string are
treated as independent requests.

### How it was discovered
The test failed with:
```
psycopg2.errors.UniqueViolation: duplicate key value
violates unique constraint "idempotency_keys_pkey"
DETAIL: Key (key)=(fs-shared-13) already exists.
```
Surprising, because the Python model already declared `merchant_id`
as part of a composite primary key, and the application code already
filtered by both columns.

### Root cause
The model file was correct, but the actual PostgreSQL table had never
been updated to match it. An earlier Alembic migration intended to
apply the composite primary key change had been generated via
`--autogenerate` and run with no errors — but inspecting the generated
migration file revealed both `upgrade()` and `downgrade()` contained
only a single `pass` statement.

Alembic's autogenerate had silently failed to detect the primary key
change and produced an empty migration, which still recorded itself
as successfully applied.

### Fix applied
Rolled back the empty migration, hand-wrote the actual DDL, and
re-applied:

```python
def upgrade() -> None:
    op.drop_constraint('idempotency_keys_pkey', 'idempotency_keys', type_='primary')
    op.create_primary_key(
        'idempotency_keys_pkey',
        'idempotency_keys',
        ['key', 'merchant_id']
    )
```

### Why this matters
Alembic's autogenerate is reliable for new tables and new columns, but
is a known weak spot for primary key constraint changes on existing
tables. It frequently produces an empty or partial migration without
raising any error.

**Lesson:** Never trust a generated migration purely because the command
exited successfully. Open the generated file and read it before running
it — especially for constraint, index, or key changes rather than
straightforward column additions.

This bug would not have been caught by unit tests that only exercised
the application layer in isolation. It only surfaced because a
scenario-level test exercised the real database constraint end-to-end —
which is a strong argument for why Phase 7's scenario tests are
valuable beyond the unit tests already in place.
