# PayFlow — Payment Orchestration Layer

<!-- 
  WHAT ARE THESE BADGES?
  These are small images that show your tech stack at a glance.
  They're generated automatically by a free service called shields.io.
  You don't need to do anything special — GitHub renders them as colored labels.
  They make your repo look professional instantly.
-->

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![Tests](https://img.shields.io/badge/Tests-84%20passing-brightgreen)

---

## What Is This?

<!-- 
  WHY THIS SECTION EXISTS:
  A recruiter has 15 seconds. This paragraph answers their first question:
  "What does this project actually do?"
  Keep it simple, clear, and focused on the REAL-WORLD problem it solves.
-->

PayFlow is a **backend payment orchestration system** — the kind of software that sits *between* 
a business's application and the actual payment gateways (like Stripe, Razorpay, UPI, PayU).

When you tap "Pay" on an app, you're talking to a system like this one. It decides:
- Which payment gateway to send your transaction to
- What to do if that gateway fails or is too slow
- How to make sure you're never charged twice for the same thing
- How to keep an accurate record of every payment's state

This project implements that entire layer from scratch — built to the specification of a 
real-world engineering challenge (Ze Theta Project 1A).

---

## Why This Project Is Interesting

<!--
  WHY THIS SECTION EXISTS:
  Most student projects are simple CRUD apps (Create, Read, Update, Delete).
  This project is genuinely more complex. This section tells a technical interviewer
  exactly what makes it worth looking at.
-->

This isn't a tutorial project — it solves real problems that production payment systems face:

| Problem | How PayFlow Solves It |
|---|---|
| User double-taps "Pay" and gets charged twice | **Idempotency service** — same request key = same result, never a duplicate charge |
| Payment gateway goes down mid-transaction | **Circuit breaker + failover routing** — automatically switches to a backup gateway |
| A webhook arrives twice (network retry) | **Webhook deduplication** — second delivery is safely ignored |
| Transaction gets stuck in an invalid state | **State machine** — enforces legal state transitions only (e.g. can't jump from AUTH_INITIATED to CAPTURED) |
| Gateway reports a different status than our records | **Reconciliation engine** — detects and corrects mismatches automatically |
| System needs to run anywhere, reliably | **Docker Compose** — one command starts the entire system |

---

## Tech Stack

<!--
  WHY THIS SECTION EXISTS:
  Interviewers and recruiters scan for keywords. This section makes your
  technologies easy to find at a glance. Each item includes a one-line
  explanation of WHY that technology was chosen — because knowing "why"
  is what separates someone who understands their project from someone
  who just followed a tutorial.
-->

| Technology | What It Does In This Project |
|---|---|
| **Python 3.11** | Main programming language |
| **FastAPI** | Web framework — handles HTTP requests, auto-generates API documentation |
| **PostgreSQL 15** | Database — stores all transactions, gateways, idempotency keys, webhooks |
| **SQLAlchemy** | ORM (Object Relational Mapper) — lets us write Python instead of raw SQL |
| **Alembic** | Database migration tool — tracks and applies changes to the database schema |
| **Pydantic** | Data validation — ensures incoming API requests have the right shape and types |
| **Docker + Docker Compose** | Containerisation — packages the entire system so it runs identically anywhere |
| **pytest** | Testing framework — 84 automated tests verify the system works correctly |

---

## System Architecture

<!--
  WHY THIS SECTION EXISTS:
  A diagram (even a text one) shows that you understand how the pieces
  connect — not just that you wrote individual files. This is the kind of
  thing that impresses technical interviewers, because it shows systems thinking.
-->

```
┌─────────────────────────────────────────────────────────┐
│                    HTTP Client                          │
│              (Swagger UI / your application)            │
└──────────────────────┬──────────────────────────────────┘
                       │  HTTP Request
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Routers                        │
│     (app/routers/) — thin layer, handles HTTP only     │
│   payments | webhooks | gateways | analytics | recon   │
└──────────────────────┬──────────────────────────────────┘
                       │  calls
                       ▼
┌─────────────────────────────────────────────────────────┐
│                 Services Layer                         │
│         (app/services/) — all business logic           │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Idempotency │  │   Router +   │  │ State Machine │  │
│  │  Service    │  │Circuit Breaker│  │               │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Webhook    │  │Reconciliation│  │Health Monitor │  │
│  │ Processor   │  │   Engine     │  │               │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │  reads/writes
                       ▼
┌─────────────────────────────────────────────────────────┐
│              PostgreSQL Database                        │
│  transactions | idempotency_keys | webhooks | gateways │
│              state_logs | refunds                      │
└─────────────────────────────────────────────────────────┘
                       │  mocked in this project
                       ▼
┌─────────────────────────────────────────────────────────┐
│             Payment Gateways (Mock)                    │
│         Stripe | Razorpay | PayU | UPI                 │
└─────────────────────────────────────────────────────────┘
```

**Key design principle:** The routers know nothing about business logic. The services know 
nothing about HTTP. This separation means each layer can be tested and changed independently.

---

## Project Structure

<!--
  WHY THIS SECTION EXISTS:
  Someone cloning your project needs to know where to look for things.
  This is especially helpful for interviewers who want to read your code.
-->

```
Ze-Theta-Payment-project/
│
├── app/                        # All application code lives here
│   ├── config.py               # Reads environment variables (database URL, secret key, etc.)
│   ├── database.py             # Sets up the database connection
│   ├── main.py                 # Entry point — registers all routers, starts FastAPI
│   ├── schemas.py              # Pydantic schemas — defines what requests/responses look like
│   │
│   ├── gateways/               # Mock payment gateways (simulate real Stripe, Razorpay, etc.)
│   │   ├── base.py             # Shared interface all gateways must follow
│   │   ├── stripe_mock.py      # Simulated Stripe gateway
│   │   ├── razorpay_mock.py    # Simulated Razorpay gateway
│   │   ├── payu_mock.py        # Simulated PayU gateway
│   │   └── upi_mock.py         # Simulated UPI gateway
│   │
│   ├── models/                 # SQLAlchemy models — each file = one database table
│   │   ├── transaction.py      # Payments table
│   │   ├── idempotency.py      # Deduplication keys table
│   │   ├── webhook.py          # Received webhooks table
│   │   ├── gateway.py          # Gateway health/config table
│   │   ├── state_log.py        # Audit log of every state change
│   │   └── refund.py           # Refunds table
│   │
│   ├── routers/                # FastAPI route handlers (HTTP layer only)
│   │   ├── payments.py         # POST /payments, GET /payments/{id}
│   │   ├── webhooks.py         # POST /webhooks/{gateway}
│   │   ├── gateways.py         # GET /gateways (health status)
│   │   ├── analytics.py        # GET /analytics (transaction stats)
│   │   └── reconciliation.py   # POST /reconciliation/run
│   │
│   └── services/               # Business logic — where decisions are made
│       ├── state_machine.py    # Enforces legal payment state transitions
│       ├── router.py           # Chooses which gateway to use for each payment
│       ├── circuit_breaker.py  # Stops routing to a failing gateway automatically
│       ├── idempotency.py      # Prevents duplicate payments
│       ├── webhook_processor.py# Verifies and processes gateway notifications
│       ├── reconciliation.py   # Finds and fixes mismatched transaction states
│       └── health_monitor.py   # Tracks gateway health scores
│
├── tests/                      # 84 automated tests
│   ├── conftest.py             # Shared test setup (database fixtures, etc.)
│   ├── test_state_machine.py   # Tests for state transition rules
│   ├── test_routing.py         # Tests for gateway selection and failover
│   ├── test_idempotency.py     # Tests for duplicate prevention
│   ├── test_webhooks.py        # Tests for webhook processing
│   ├── test_reconciliation.py  # Tests for reconciliation engine
│   ├── test_gateways.py        # Tests for mock gateways
│   └── test_scenarios.py       # End-to-end tests for 13 named failure scenarios
│
├── migrations/                 # Alembic database migrations
│   └── versions/               # Each file = one change to the database schema
│
├── docs/
│   └── state-machine.md        # Documentation for the payment state machine
│
├── Dockerfile                  # Instructions to build the app into a container
├── docker-compose.yml          # Starts the entire system (app + database) with one command
├── requirements.txt            # Python packages this project depends on
├── pytest.ini                  # pytest configuration
└── alembic.ini                 # Alembic (database migration) configuration
```

---

## How to Run This Project

<!--
  WHY THIS SECTION EXISTS:
  Ze Theta's grader will run your project. So will anyone evaluating your
  work. Clear instructions mean your project actually gets evaluated
  instead of getting skipped because "it didn't work."
  
  We offer TWO options: Docker (recommended, works on any machine) and
  local (for development). Docker is what Ze Theta uses.
-->

### Option 1: Docker (Recommended — this is what Ze Theta uses)

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

```bash
# Step 1: Clone the repository
git clone https://github.com/Suraj-Raj-7/Ze-Theta-Payment-project.git
cd Ze-Theta-Payment-project

# Step 2: Start the entire system (database + app) with one command
docker-compose up

# That's it. Docker will:
# 1. Start a PostgreSQL database
# 2. Wait for the database to be healthy
# 3. Run all database migrations automatically
# 4. Start the FastAPI server on port 8000
```

Once running, open your browser and go to:
- **API Documentation (Swagger UI):** http://localhost:8000/docs
- **Alternative API Docs (ReDoc):** http://localhost:8000/redoc

To stop: press `Ctrl+C` in the terminal, then run `docker-compose down`

---

### Option 2: Local Development (without Docker)

**Prerequisites:** Python 3.11+, PostgreSQL running locally.

```bash
# Step 1: Clone the repository
git clone https://github.com/Suraj-Raj-7/Ze-Theta-Payment-project.git
cd Ze-Theta-Payment-project

# Step 2: Create a virtual environment
# (This keeps this project's packages separate from your other Python projects)
python -m venv venv

# Step 3: Activate the virtual environment
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Step 4: Install all required packages
pip install -r requirements.txt

# Step 5: Set up environment variables
# Copy the example file and fill in your database details
copy .env.example .env      # Windows
# cp .env.example .env      # Mac/Linux
# Then edit .env with your PostgreSQL credentials

# Step 6: Apply database migrations (creates all tables)
alembic upgrade head

# Step 7: Start the server
uvicorn app.main:app --reload
```

---

## Environment Variables

<!--
  WHY THIS SECTION EXISTS:
  Real applications never hardcode passwords or secrets into the code.
  Instead, they use environment variables — values set outside the code
  that the application reads at runtime. This is a security best practice.
  
  We explain what each variable does so anyone running the project knows
  what to set.
-->

Create a `.env` file in the project root with these values:

```env
# Your PostgreSQL connection string
# Format: postgresql://username:password@host:port/database_name
DATABASE_URL=postgresql://payflow_user:payflow_pass@localhost:5432/payflow_db

# A secret key used for cryptographic operations (webhook signature verification)
# In production, this should be a long random string — never share it
SECRET_KEY=your-secret-key-here

# Set to True during development to see detailed error messages
# Always False in production
DEBUG=True
```

See `.env.example` in the repository for a template.

---

## API Endpoints

<!--
  WHY THIS SECTION EXISTS:
  A table of endpoints tells a technical reader exactly what your API
  can do. It's also proof that you built a real REST API, not just scripts.
-->

### Payments

| Method | Endpoint | What It Does |
|---|---|---|
| `POST` | `/api/v1/payments` | Create and route a new payment |
| `GET` | `/api/v1/payments/{id}` | Get a payment's current status |

### Webhooks
| Method | Endpoint | What It Does |
|---|---|---|
| `POST` | `/api/v1/webhooks/razorpay` | Receive Razorpay payment notifications |
| `POST` | `/api/v1/webhooks/stripe` | Receive Stripe payment notifications |
| `POST` | `/api/v1/webhooks/payu` | Receive PayU payment notifications |
| `POST` | `/api/v1/webhooks/upi` | Receive UPI payment notifications |

### Gateways

| Method | Endpoint | What It Does |
|---|---|---|
| `GET` | `/api/v1/gateways` | View all gateways and their health status |

### Analytics

| Method | Endpoint | What It Does |
|---|---|---|
| `GET` | `/api/v1/analytics` | View transaction statistics and success rates |

### Reconciliation
| Method | Endpoint | What It Does |
|---|---|---|
| `POST` | `/api/v1/reconciliation/trigger` | Manually trigger a reconciliation run |
---

## Key Features Explained

<!--
  WHY THIS SECTION EXISTS:
  Features listed as bullet points look shallow. Explaining HOW each feature
  works shows technical depth — which is what gets you job interviews.
-->

### Idempotency (Duplicate Payment Prevention)
Every payment request carries a unique client-generated key. If the same key is submitted 
twice (e.g. a user double-tapping "Pay", or a client retrying after a network timeout), 
the system returns the original result without creating a second charge. If a payment 
previously failed, the same key can be retried — the existing record is updated rather 
than a duplicate being created.

### Circuit Breaker + Intelligent Routing
The routing engine scores each gateway based on recent success rate, response time, and 
configured priority. If a gateway's failure rate crosses a threshold, the circuit breaker 
opens — the gateway is temporarily removed from rotation and traffic is automatically 
redirected to healthy alternatives. This prevents a single failing gateway from 
degrading the entire system.

### Payment State Machine
Every transaction follows a strict lifecycle:

```
INITIATED → AUTH_INITIATED → AUTHORISED → CAPTURE_INITIATED → CAPTURED → SETTLED
                           ↘ AUTH_FAILED
                           ↘ AUTH_TIMEOUT
```

The state machine enforces that no illegal jumps can occur. A webhook claiming a 
transaction jumped from `AUTH_INITIATED` directly to `CAPTURED` will be rejected — 
protecting against both bugs and malicious inputs.

### Webhook Processing Pipeline
Incoming gateway webhooks are: (1) signature-verified to confirm they're genuine, 
(2) checked against a deduplication store to safely ignore repeated deliveries, 
and (3) used to drive state machine transitions. Invalid transitions are rejected 
gracefully without crashing.

### Reconciliation Engine
A background process compares each transaction's internally-recorded status against 
what the gateway actually reports. Discrepancies (e.g. our system shows CAPTURE_INITIATED 
but the gateway reports CAPTURED) are automatically corrected via the state machine, 
and logged for audit purposes.

---

## Test Coverage

<!--
  WHY THIS SECTION EXISTS:
  84 tests is genuinely impressive for a student project. Many professional
  projects have worse test coverage. Saying this clearly turns a number into
  a signal of engineering quality.
-->

```
84 tests — 0 failing
```

Tests are organised by layer:

| Test File | What It Covers | Tests |
|---|---|---|
| `test_state_machine.py` | Legal/illegal state transitions | ~15 |
| `test_routing.py` | Gateway selection, failover, circuit breaker | ~20 |
| `test_idempotency.py` | Duplicate prevention, retry logic | ~10 |
| `test_webhooks.py` | Signature verification, deduplication, transitions | ~12 |
| `test_reconciliation.py` | Stale detection, correction, graceful failures | ~10 |
| `test_gateways.py` | Mock gateway behaviour | ~5 |
| `test_scenarios.py` | 13 named end-to-end failure scenarios (from spec) | ~13 |

Run the full test suite:

```bash
# Make sure your virtual environment is active first
pytest

# To see more detail about each test:
pytest -v

# To see a coverage report:
pytest --cov=app
```

---

## Engineering Decisions Worth Noting

<!--
  WHY THIS SECTION EXISTS:
  This is the section that separates "I built a project" from "I understand
  why I made each decision." Technical interviewers love this section.
  It's essentially pre-answering their questions.
-->

**Why keep routers thin?**
Route handlers in `app/routers/` do almost no work themselves — they call services and 
translate results into HTTP responses. This means all business logic (idempotency, routing, 
state transitions) was fully testable from plain Python before a single HTTP endpoint existed.

**Why SQLAlchemy over raw SQL?**
SQLAlchemy lets us write Python objects instead of SQL strings, which reduces the chance 
of SQL injection bugs and makes the code easier to read. The tradeoff is an extra layer 
of abstraction — but for a project of this size, the safety and readability gains outweigh it.

**Why mock gateways instead of real ones?**
Real payment gateways require API keys, network access, and money. Mock gateways let the 
routing, failover, and circuit breaker logic be tested deterministically — we can simulate 
a gateway failing on command, which you can't do with a real gateway in a test environment.

**Why Alembic for migrations?**
Without a migration tool, database changes are applied manually and inconsistently across 
environments. Alembic tracks every schema change as a versioned file — so running 
`alembic upgrade head` on any machine produces an identical database.

---

## About This Project

Built as part of the Ze Theta Project 1A engineering challenge — a real-world backend 
specification requiring a production-grade payment orchestration layer with Docker deployment, 
comprehensive test coverage, and resilience against 15 named failure scenarios.

---

*Built with Python, FastAPI, PostgreSQL, and Docker.*
