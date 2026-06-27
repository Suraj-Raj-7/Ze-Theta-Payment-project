# Changelog — PayFlow Payment Orchestration Layer

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] — 2026-06-27

### Summary
Complete implementation of the Ze Theta Project 1A specification: a
production-grade payment orchestration back-end with multi-gateway routing,
automatic failover, idempotency protection, webhook processing, and
background reconciliation.

---

### Day 1–2: Architecture & Database Design

- Designed complete database schema: 8 tables across models/
- Created initial Alembic migration (21f1c1209d8d) — all tables created cleanly
- Wrote `docs/state-machine.md` with full Mermaid state diagram (23 states)
- Wrote `docs/architecture.md` covering all six core components
- Wrote `docs/ADR-001-language.md` explaining Python + FastAPI choice
- Set up project skeleton: FastAPI app, SQLAlchemy engine, Alembic config

### Day 3–4: Transaction State Machine & Core Models

- Implemented `TransactionStatus` enum with 23 states (all required by spec plus extras)
- Implemented `VALID_TRANSITIONS` rulebook covering all legal state moves
- Implemented `TransactionStateMachine.transition()` — single gatekeeper for all state changes
- Implemented immutable audit trail: every transition writes one row to `transaction_state_logs`
- Implemented `Transaction`, `TransactionStateLog`, `Refund` models
- Wrote 16 unit tests covering valid transitions, invalid rejections, terminal states
- Fixed Bug: idempotency retry path was falling through to INSERT instead of UPDATE (Phase 4 Bug 1)

### Day 5–6: Gateway Adapter Layer

- Implemented abstract `PaymentGateway` base class (Strategy pattern)
- Implemented `RazorpayMockGateway`, `StripeMockGateway`, `PayUMockGateway`, `UPIMockGateway`
- Each mock gateway respects all 5 control headers from spec (B4.3):
  - `X-Mock-Response: success / decline / timeout / server-error / rate-limit`
  - `X-Mock-Gateway-Down: true`
  - `X-Mock-Delay-Ms: N`
- UPI gateway correctly implements instant-settle flow (no separate capture phase)
- Wrote 8 parametrised gateway tests × 4 gateways = 32 gateway tests

### Day 7–8: Routing Algorithm & Circuit Breaker

- Implemented `GatewayHealthMonitor` with 100-request sliding window per gateway
- Implemented weighted scoring formula from spec Section A3.2 (5 factors, configurable weights)
- Implemented hard filter by payment method before scoring
- Implemented `GatewayCircuitBreaker` with CLOSED → OPEN → HALF_OPEN state machine
- Implemented `execute_authorize_with_failover()` — automatic retry on next-best gateway
- Wrote `docs/routing-algorithm.md` with worked example (₹450 UPI payment)
- Wrote 20+ routing and circuit breaker tests

### Day 9–10: Idempotency & Webhook Processing

- Implemented `IdempotencyService` with PROCESSING / COMPLETED / FAILED lifecycle
- Implemented webhook signature verification (HMAC-SHA256 with `hmac.compare_digest`)
- Implemented webhook deduplication via `processed_webhook_events` table
- Implemented `process_webhook()` pipeline: verify → deduplicate → apply state transition
- Handled out-of-order webhook delivery gracefully (invalid transitions rejected, not crashed)
- Fixed Bug: webhook "failure" was actually the state machine correctly rejecting bad test data (Phase 4 Bug 2)
- Wrote 12 webhook tests covering signature validation, deduplication, transitions

### Day 11–12: API Layer & Reconciliation Engine

- Implemented all 23 API endpoints specified in Section A7.1
- Implemented `run_reconciliation()`: find stale → poll gateway → correct or flag
- Integrated APScheduler: reconciliation runs automatically every 15 minutes
- Implemented `POST /api/v1/reconciliation/trigger` for on-demand runs
- Wrote `docs/api-specification.yaml` (OpenAPI 3.0)
- Fixed Bug: reconciliation logged "was X, now X" because `txn.status` was read after mutation (Phase 6 Bug 1)
- Wrote 10 reconciliation tests

### Day 13: Failure Scenario Testing

- Wrote `tests/test_scenarios.py` with 13 named end-to-end scenario tests (FS-01 through FS-15)
- All 13 implemented scenarios pass
- FS-07 (triple simultaneous gateway cascade) and FS-14 (connection pool exhaustion) marked for load-test tooling
- Discovered and fixed: idempotency composite primary key existed in Python model but not in database (Phase 7 Bug 1)
- Applied hand-written Alembic migration (ca94b3ed0380) to fix the composite PK
- Documented all bugs in `docs/errors-found.md`
- Full test suite: 84 tests, 0 failing

### Day 14: Docker, Documentation & Performance

- Created `Dockerfile` (python:3.13-slim, auto-runs migrations on startup)
- Created `docker-compose.yml` with PostgreSQL 15 health check before app starts
- Verified `docker-compose up` starts entire system from scratch with zero manual steps
- Finalised `README.md` with architecture diagram, setup instructions, API reference
- Finalised all docs: architecture.md, state-machine.md, routing-algorithm.md, api-specification.yaml
- Added `.env.example` template

### Day 15: Final Review & Submission

- Ran full test suite: 84 tests passing, 0 failures
- Identified 5 deliberate errors planted in Ze Theta spec (documented in `docs/errors-found.md`)
- Code cleanup: no dead code, no debug print statements, consistent formatting
- Docker deployment verified from clean state
- Repository prepared for transfer to ZethetaIntern

---

### What Was Built

| Component | Location | Tests |
|---|---|---|
| Payment state machine (23 states) | `app/services/state_machine.py` | `test_state_machine.py` |
| 4 mock gateways (Stripe, Razorpay, PayU, UPI) | `app/gateways/` | `test_gateways.py` |
| Intelligent routing algorithm | `app/services/router.py` | `test_routing.py` |
| Circuit breaker (CLOSED/OPEN/HALF_OPEN) | `app/services/circuit_breaker.py` | `test_routing.py` |
| Idempotency service | `app/services/idempotency.py` | `test_idempotency.py` |
| Webhook processing pipeline | `app/services/webhook_processor.py` | `test_webhooks.py` |
| Reconciliation engine | `app/services/reconciliation.py` | `test_reconciliation.py` |
| 23 REST API endpoints | `app/routers/` | `test_scenarios.py` |
| Docker Compose deployment | `docker-compose.yml`, `Dockerfile` | — |
| OpenAPI 3.0 specification | `docs/api-specification.yaml` | — |

### Test Coverage Summary

```
84 tests — 0 failing

test_state_machine.py    16 tests
test_routing.py          ~20 tests
test_idempotency.py      ~10 tests
test_webhooks.py         ~12 tests
test_reconciliation.py   ~10 tests
test_gateways.py         ~8 tests (32 parametrised)
test_scenarios.py        13 named failure scenario tests
```

### Known Limitations

- FS-07 (cascade failure: all three non-UPI gateways failing simultaneously): components are all built and tested individually; a dedicated load-testing script with k6 would demonstrate the combined behaviour more convincingly than a unit test can.
- FS-14 (connection pool exhaustion under flash sale load): requires a load-testing tool (k6 or Locust) to simulate 180,000 concurrent requests honestly. Cannot be meaningfully demonstrated in a unit test.
