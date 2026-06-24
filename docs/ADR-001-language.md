# ADR-001: Choice of Programming Language and Framework

**ADR** = Architecture Decision Record. This document records ONE
specific decision made during the project: why Python + FastAPI was
chosen. It explains the reasoning so future readers understand why
the project is built the way it is, not just what it's built with.

---

## Status

Accepted — implemented across all phases.

---

## Context

The Ze Theta Project 1A specification required building a backend
payment orchestration layer. The choice of language and framework
was left open. The decision needed to consider:

- Speed of development (this is a solo project with a deadline)
- Quality of database tooling (PostgreSQL integration)
- API documentation (the grader needs to test endpoints)
- Testability (the spec requires proving 15 failure scenarios)
- Docker compatibility (required for submission)

---

## Decision

**Language:** Python 3.11  
**Web framework:** FastAPI  
**ORM:** SQLAlchemy  
**Validation:** Pydantic  

---

## Reasons

### Why Python over Node.js or Java?

**Against Node.js:**
Node.js is fast for I/O-heavy work, but its async model (callbacks,
Promises, async/await) adds complexity when the priority is writing
clear, readable business logic. Python's synchronous code reads more
naturally for a state machine and routing algorithm where the logic
matters more than raw throughput.

**Against Java/Spring Boot:**
Java and Spring Boot are the industry standard for payment systems
at large companies. However, Spring Boot's setup overhead (annotations,
bean configuration, application context) is significant for a solo
project. Python reaches a working prototype faster without sacrificing
correctness.

**For Python:**
- SQLAlchemy is one of the most mature ORMs available in any language
- pytest fixtures make database test isolation clean and readable
- The standard library includes `hmac`, `hashlib`, `uuid`, `datetime`
  — everything needed for payment security without extra dependencies
- Readable code means the business logic (state machine, routing
  formula) is easier to verify as correct during code review

### Why FastAPI over Flask or Django?

**Against Flask:**
Flask is minimal by design — it provides routing and nothing else.
Pydantic validation, OpenAPI documentation, and async support all
require separate libraries and configuration. For a project that
needs all three, this adds boilerplate.

**Against Django:**
Django is a full-stack framework designed around the Django ORM and
Django templates. This project uses SQLAlchemy (not Django ORM) and
has no templates (pure API). Using Django for a pure API service
means working against the framework's conventions.

**For FastAPI:**
- Pydantic schemas automatically become OpenAPI documentation —
  the Swagger UI at `/docs` is generated for free, which means the
  Ze Theta grader can test every endpoint interactively
- Request validation is built in: a payment request with a negative
  amount is rejected before the route handler even runs
- FastAPI is explicit about the separation between HTTP handling
  (routers) and business logic (services) — which matches the
  three-layer architecture this project uses
- Async support (via Starlette) is available when needed without
  requiring the entire application to be async

### Why SQLAlchemy over raw SQL or Django ORM?

Raw SQL is error-prone (SQL injection risk, string formatting bugs)
and couples the application tightly to PostgreSQL's specific syntax.

Django ORM requires Django, which was ruled out above.

SQLAlchemy provides:
- A Pythonic query interface that's still close to SQL when needed
- Alembic for versioned database migrations
- Session management that makes test isolation clean
- JSONB column support for storing gateway responses

---

## Consequences

**Positive:**
- FastAPI's Swagger UI made live end-to-end testing possible without
  writing a separate test client (demonstrated in Phase 5)
- pytest fixtures with SQLAlchemy sessions kept 84 tests isolated
  and deterministic
- Python's `hmac` module provided constant-time signature comparison
  (`hmac.compare_digest`) out of the box — no third-party crypto library
  needed for webhook signature verification

**Negative:**
- Python is slower than Java or Go for CPU-bound work. For a payment
  system at real scale, this would matter. For this project's scope
  (correctness over throughput), it does not.
- Python's GIL (Global Interpreter Lock) limits true parallelism.
  In production, this is solved by running multiple uvicorn workers
  behind a load balancer — which Docker Compose can be extended to do.

---

## Alternatives Considered and Rejected

| Option | Reason Rejected |
|---|---|
| Node.js + Express | Async complexity outweighs I/O speed benefit at this scale |
| Java + Spring Boot | Setup overhead too high for solo project timeline |
| Go + Gin | No ORM as mature as SQLAlchemy; steeper learning curve |
| Flask + SQLAlchemy | Missing auto-documentation and built-in validation |
| Django + DRF | Framework conventions conflict with SQLAlchemy and pure API design |
