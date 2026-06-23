# PayFlow — System Architecture

> This document explains HOW the system is designed and WHY each
> decision was made. It is written for two audiences:
> 1. A developer who wants to understand the codebase quickly
> 2. An interviewer asking "walk me through your system design"

---

## The One-Line Summary

PayFlow sits **between** a merchant's application and multiple payment
gateways (Stripe, Razorpay, PayU, UPI). It decides which gateway to use,
protects against duplicate charges, verifies incoming notifications, and
automatically corrects records when something goes wrong.

---

## Why Does This Layer Exist?

Without an orchestration layer, a merchant's application would need to:

- Know which gateway to call for each payment method
- Handle gateway failures and retries manually
- Prevent double charges when a user taps "Pay" twice
- Verify that payment notifications are genuine
- Detect when a transaction got stuck and never resolved

PayFlow handles all of this so the merchant's app only needs to make
one simple API call: `POST /api/v1/payments`.

---

## The Three-Layer Design

This is the most important architectural decision in the project.
Every file belongs to exactly one of three layers:

```
┌─────────────────────────────────────────┐
│           LAYER 1: HTTP Layer           │
│              app/routers/               │
│  "Translate HTTP into function calls"   │
│  Knows about: requests, responses,      │
│  status codes, headers                  │
│  Does NOT know about: business rules    │
└──────────────────┬──────────────────────┘
                   │ calls
                   ▼
┌─────────────────────────────────────────┐
│        LAYER 2: Business Logic          │
│             app/services/               │
│   "Make all the decisions"              │
│  Knows about: payment rules, state      │
│  machine, routing, idempotency          │
│  Does NOT know about: HTTP at all       │
└──────────────────┬──────────────────────┘
                   │ reads/writes
                   ▼
┌─────────────────────────────────────────┐
│          LAYER 3: Data Layer            │
│    app/models/ + PostgreSQL database    │
│   "Store and retrieve information"      │
│  Knows about: tables, columns, queries  │
│  Does NOT know about: HTTP or rules     │
└─────────────────────────────────────────┘
```

**Why this separation matters (this is an interview answer):**

Before this project had any HTTP endpoints (Phases 1-4), the entire
business logic was already written and fully tested from a plain Python
terminal. The state machine, routing algorithm, circuit breaker, and
idempotency service all worked before a single API endpoint existed.

This is only possible because the services layer has zero knowledge of
HTTP. If business logic was mixed into route handlers, you could not
test it without running a server.

---

## The Six Core Components

### 1. Payment State Machine (`app/services/state_machine.py`)

**What it does:** Every payment goes through a lifecycle. The state
machine is the single gatekeeper that controls which step a payment
is allowed to move to next.

**Why it exists:** Without it, any bug anywhere in the codebase could
set a payment to any status — for example, marking a payment as
REFUNDED when no money was ever actually captured. In financial
systems, this is not acceptable.

**How it works:**
```
CREATED → ROUTE_SELECTED → AUTH_INITIATED → AUTHORISED → CAPTURE_INITIATED → CAPTURED → SETTLED
                                          ↘ AUTH_FAILED → (retry or FAILED)
                                          ↘ AUTH_TIMEOUT → (retry or FAILED)
```

The full state diagram is documented in `docs/state-machine.md`.

**Key design decision:** The `transition()` method is the ONLY place
in the entire codebase where a transaction's status is ever changed.
No other code does `transaction.status = X` directly. This guarantee
is what makes the audit log complete and tamper-evident.

**Every transition is logged.** The `transaction_state_logs` table
records every state change with a timestamp, what caused it, and the
gateway's response. This is insert-only — rows are never updated or
deleted. This is a financial audit trail requirement.

---

### 2. Gateway Router + Circuit Breaker (`app/services/router.py` + `app/services/circuit_breaker.py`)

**What it does:** Chooses which payment gateway (Stripe, Razorpay,
PayU, UPI) to use for each payment, and automatically stops routing
to a gateway that keeps failing.

**Why it exists:** Different gateways have different costs, speeds,
and supported payment methods. Routing to the cheapest gateway that
supports UPI, for example, saves money at scale. And if Razorpay is
having an outage, the system should automatically use PayU instead —
without any human intervention.

**How the scoring works:**

Each gateway gets a score from 0 to 1 based on five factors:

```
Score = (success_rate × 0.35)    ← most important: does it actually work?
      + (speed       × 0.20)    ← how fast is it?
      + (cost        × 0.20)    ← how cheap is it?
      + (health      × 0.15)    ← is the circuit breaker open?
      + (fit         × 0.10)    ← does it support this payment method?
```

The weights (0.35, 0.20 etc.) come from the project specification
(Ze Theta PDF Section A3.1). In a real system these would be
configurable in a database table, not hardcoded.

**How the circuit breaker works:**

Think of an electrical circuit breaker in your house. When there's a
power surge, the breaker "trips" (opens) and stops electricity flowing
to protect the house. It resets after a while.

A software circuit breaker does the same thing:

```
CLOSED (normal) → 5 consecutive failures → OPEN (stopped)
OPEN → 30 seconds pass → HALF_OPEN (testing)
HALF_OPEN → one success → CLOSED (back to normal)
HALF_OPEN → one failure → OPEN (stopped again)
```

When a gateway's circuit is OPEN, the router skips it entirely and
picks the next best gateway. This prevents wasting time on a gateway
that is clearly having an outage.

**Failover:** If the first gateway fails, the router automatically
tries the next best available gateway, up to 3 attempts. This is
transparent to the merchant — they just see a successful payment,
not which gateway was actually used.

---

### 3. Idempotency Service (`app/services/idempotency.py`)

**What it does:** Guarantees that a payment is only processed once,
even if the same request is sent multiple times.

**Why it exists:** Networks are unreliable. A user might tap "Pay"
twice. A client might retry after a timeout. Without idempotency,
each retry would create a separate charge — the user gets charged
twice for one order. This is called a "double charge" and is one of
the most damaging bugs a payment system can have.

**How it works:**

Every payment request includes a client-generated `idempotency_key`
— a unique string for that specific payment attempt (e.g. a UUID).

```
Request comes in with key "abc123"
    │
    ├── Key seen before, status=PROCESSING → reject (409, already in progress)
    ├── Key seen before, status=COMPLETED  → return original response (no new charge)
    ├── Key seen before, status=FAILED     → allow retry (update existing row)
    └── Key never seen  → process normally, store key
```

**The race condition protection:**

Imagine two network retries arriving at exactly the same millisecond.
Both check the database, both see no existing row, both try to insert.
PostgreSQL's PRIMARY KEY constraint on `(key, merchant_id)` means only
one INSERT can succeed — the other gets a database-level error, which
the code catches and converts into a "already in progress" response.
This is race-safe without any application-level locking.

**Multi-tenant isolation:** The primary key is `(key, merchant_id)`
not just `key`. This means Merchant A and Merchant B can both use
the key "order-123" without any collision. This was discovered missing
in Phase 7 (the Alembic migration had silently produced an empty
migration — see `docs/errors-found.md`).

---

### 4. Webhook Processor (`app/services/webhook_processor.py`)

**What it does:** Receives asynchronous notifications from payment
gateways (e.g. "payment succeeded"), verifies they are genuine, and
applies the corresponding state transition.

**Why webhooks exist:** When you call a gateway's authorize API, it
might respond "processing" rather than "success" or "fail" immediately.
The gateway then calls your webhook endpoint later when it has a final
answer. This is common with UPI and netbanking payments.

**The three-step pipeline:**

```
Step 1: VERIFY SIGNATURE
        Recompute expected HMAC-SHA256 signature using shared secret.
        Compare with the signature in the request header.
        If they don't match → reject with 401. Could be an attacker.

Step 2: DEDUPLICATE
        Check if this event_id was already processed.
        If yes → return "duplicate_ignored". Safe to ignore.
        Gateways routinely resend webhooks to ensure delivery.

Step 3: APPLY STATE TRANSITION
        Look up the transaction by gateway_payment_id.
        Map the gateway's event type to our internal state.
        Call state_machine.transition() to apply it.
        If the transition is invalid → log it, don't crash.
```

**Why HMAC-SHA256 and not a simple password?**

HMAC (Hash-based Message Authentication Code) proves both that the
sender knows the shared secret AND that the message content was not
tampered with in transit. A simple password check only proves the
first. The `hmac.compare_digest()` function is used instead of `==`
because it runs in constant time regardless of where the mismatch is
— this prevents timing attacks.

---

### 5. Reconciliation Engine (`app/services/reconciliation.py`)

**What it does:** A background process that periodically finds
transactions stuck in intermediate states and corrects them.

**Why it exists:** Webhooks can fail to arrive. A network outage
during a gateway call might leave a transaction in `AUTH_INITIATED`
forever, never getting the "success" or "fail" webhook it was waiting
for. The reconciliation engine is the safety net that catches these.

**How it works:**

```
Every 15 minutes (via APScheduler in app/main.py):

1. Find transactions stuck in AUTH_INITIATED or CAPTURE_INITIATED
   for more than 5 minutes

2. For each one: call the gateway's get_status() API directly
   (polling, as opposed to waiting for a webhook)

3. Compare what the gateway says with what our database says:
   - Same state → confirmed consistent, no action needed
   - Different state → apply correction via state machine
   - Can't reconcile → flag as anomaly for manual review

4. Return a summary: checked=N, corrected=M, anomalies=P
```

**A real bug found here (Phase 6):** When logging "was X, now Y",
the code originally read `txn.status` for the "was" value AFTER
calling `sm.transition()` — which had already mutated the object.
So both sides showed the new value. Fixed by capturing
`original_state = txn.status` BEFORE the transition call.
See `docs/errors-found.md` for the full story.

---

### 6. Mock Gateways (`app/gateways/`)

**What they are:** Simulated versions of real payment gateways
(Stripe, Razorpay, PayU, UPI) that behave like the real thing but
don't move any actual money.

**Why mocks instead of real gateways?**

Real gateways require API keys, live credentials, and network access.
They also can't be made to fail on command — you can't tell Razorpay
"please simulate a timeout for this test."

Mock gateways accept special HTTP headers to simulate any condition:

```python
X-Mock-Response: "success"      # normal success
X-Mock-Response: "decline"      # card declined
X-Mock-Response: "timeout"      # gateway timeout
X-Mock-Response: "server-error" # gateway HTTP 502
X-Mock-Gateway-Down: "true"     # gateway completely unreachable
```

This makes it possible to test every failure scenario deterministically.
The circuit breaker, failover routing, and reconciliation engine were
all built and verified entirely using mock gateways.

**The abstract base class (`app/gateways/base.py`):**

All four gateways inherit from `PaymentGateway(ABC)`, which defines
four methods every gateway must implement: `authorize()`, `capture()`,
`refund()`, `get_status()`. This is the **Strategy pattern** — the
router can call `gateway.authorize()` without knowing or caring whether
it's talking to Stripe or UPI. They all have the same interface.

---

## Database Schema

Eight tables, each with a clear single responsibility:

| Table | Purpose |
|---|---|
| `transactions` | One row per payment attempt. The central table. |
| `transaction_state_logs` | Insert-only audit trail of every state change |
| `idempotency_keys` | Stores processed request keys to prevent duplicates |
| `processed_webhook_events` | Stores processed webhook IDs to prevent duplicate processing |
| `webhook_events` | Incoming webhook storage (for retry/audit purposes) |
| `gateway_configs` | Configuration per gateway (cost, timeout, rate limit) |
| `gateway_health_metrics` | Historical health snapshots per gateway |
| `refunds` | One row per refund attempt, linked to a transaction |

**Why PostgreSQL and not SQLite?**

SQLite is a file-based database that doesn't support concurrent
writes safely. For a payment system where multiple requests arrive
simultaneously, this matters. PostgreSQL handles concurrent writes
correctly, supports JSONB for flexible gateway response storage,
and enforces constraints (like composite primary keys) that protect
against race conditions at the database level — not just in Python.

---

## Why FastAPI?

FastAPI was chosen over Flask or Django for three reasons:

1. **Automatic API documentation.** FastAPI reads the Pydantic schemas
   and generates a live, interactive Swagger UI at `/docs` with zero
   extra code. This means you can test every endpoint in a browser
   without writing a separate test client.

2. **Pydantic validation is built in.** If a payment request arrives
   with a negative amount, FastAPI rejects it before the route handler
   even runs. No manual `if amount <= 0: raise error` checks needed.

3. **Performance.** FastAPI is one of the fastest Python web frameworks,
   built on Starlette and async Python. For I/O-heavy work like calling
   payment gateways, async matters.

---

## Why Docker?

The problem Docker solves: "it works on my machine."

Without Docker, running this project on another computer requires:
installing the right Python version, installing PostgreSQL, creating
the database, running migrations, setting environment variables...
This is fragile and error-prone.

With Docker Compose, the entire system starts with one command:
```bash
docker-compose up
```

Docker handles: starting PostgreSQL, waiting for it to be healthy,
running all database migrations, and starting the FastAPI server —
automatically, identically, on any machine. This is how Ze Theta's
grader runs the project.

---

## Key Engineering Lessons From Building This

These are the real bugs and decisions worth knowing:

**1. ORM mutation trap (Phase 4)**
After calling `sm.transition()`, reading `txn.status` gives you the
NEW value, not the old one — SQLAlchemy mutates the object in place.
Always capture values you need before a mutating call.

**2. Alembic's autogenerate doesn't detect primary key changes (Phase 7)**
A migration that adds columns works fine with autogenerate. A migration
that changes a primary key from single to composite silently produced
an empty migration file. The lesson: always read the generated migration
file before running it.

**3. A rejected operation is not always a bug (Phase 4)**
When testing the webhook pipeline, a "transition rejected" error looked
like a failure. But reading the error message showed it was the state
machine correctly rejecting an impossible transition — the test data
was unrealistic. The safety mechanism was working correctly.

**4. Test isolation matters (Phase 6)**
Manual testing against a real database leaves data behind. The
reconciliation engine found transactions from previous sessions during
testing. Every automated test fixture cleans up its own rows on teardown.

---

## Failure Scenarios Proven

The project was tested against 13 of 15 named failure scenarios from
the Ze Theta specification. The two not implemented:

- **FS-07** (three simultaneous gateway failures): deprioritised under
  time constraints; the components that would prove it are all built.
- **FS-14** (connection pool exhaustion): requires a load-testing tool
  like k6 or Locust to demonstrate honestly. A unit test cannot simulate
  thousands of concurrent connections.

---

*For the payment state machine diagram and transition table,
see `docs/state-machine.md`.*

*For the routing algorithm weight calculations,
see `docs/routing-algorithm.md`.*
