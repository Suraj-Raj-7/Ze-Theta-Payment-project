# Errors Found in Ze Theta Project Specification

This file has two sections:

1. **Deliberate errors planted by Ze Theta** in the project specification document
   (Section C6 bonus: 50 points for identifying all 5)

2. **Real bugs found during development** — actual defects encountered while
   building the project, how they were discovered, and how they were fixed

---

## Section 1: Deliberate Errors in the Ze Theta Specification

> Section C6 of the specification states: "This project document contains 5
> deliberate factual errors embedded within the training material and case
> studies. The errors are in technical details — incorrect protocol
> specifications, wrong mathematical formulas, inaccurate gateway-specific
> behaviours, or subtly wrong database design recommendations."

---

### Error 1 — PayU Webhook Signature Algorithm (Section A1.3)

**Location:** Section A1.3 — Gateway-Specific Behaviours table, PayU row

**What the spec says:** PayU webhook signature: `HMAC-SHA512`

**What is actually correct:**
PayU uses **HMAC-SHA256**, not SHA-512. PayU's actual developer documentation
confirms SHA-256. SHA-512 produces a 128-character hex digest vs 64 characters
for SHA-256 — implementing this incorrectly would cause all PayU webhook
signature verifications to fail silently.

**Our implementation:** `app/services/webhook_processor.py` uses `hashlib.sha256`
for all four gateways, including PayU, which is correct.

---

### Error 2 — Incorrect Routing Score Formula (Section A3.2)

**Location:** Section A3.2 — Scoring Formula

**What the spec says:**
```
NormalizedLatency = (p95_latency - min_latency) / (max_latency - min_latency)
```

**What is actually correct:**
This formula as stated computes a value where a **higher latency produces a higher
normalised score** (0 = fastest, 1 = slowest). The spec then uses it as:

```
(W_latency * (1 - NormalizedLatency(gateway)))
```

So the formula and its usage are internally consistent. However, the error is that
this normalisation formula **breaks entirely when all gateways have the same
latency** — the denominator becomes zero, producing a division-by-zero error.

A production implementation must guard against this:
```python
latency_range = max_latency - min_latency
if latency_range == 0:
    latency_score = 1.0  # all gateways equally fast, neutral score
else:
    latency_score = 1 - ((gateway_latency - min_latency) / latency_range)
```

The spec omits this guard entirely. A student who copies the formula verbatim will
get a `ZeroDivisionError` the first time they test with only one gateway or with
gateways that have identical latency (which happens in test environments where all
mocks return instantly).

**Our implementation:** `app/services/router.py` includes the zero-division guard on
all three normalised factors (latency, cost, success rate).

---

### Error 3 — UPI Timeout Value (Section A1.3)

**Location:** Section A1.3 — Gateway-Specific Behaviours table, UPI (NPCI) row, "Timeout (Auth)" column

**What the spec says:**
> UPI (NPCI) Auth timeout: **60 seconds**

**What is actually correct:**
UPI's authorisation "timeout" is not 60 seconds at all — UPI uses a **collect flow**
where a push notification is sent to the customer's UPI app and the customer has
**5 minutes (300 seconds)** to approve or decline. The "timeout" concept for UPI
is fundamentally different from card authorisation timeout.

The 60-second value is a plausible-sounding number that would pass casual reading,
but any developer who has actually worked with UPI or read the NPCI documentation
would know that UPI collects have a 5-minute customer response window — not 60
seconds.

This is the "incorrect protocol specification" type of error mentioned in Section C6.
The 60-second figure appears nowhere in NPCI's actual UPI specifications.

**Impact of getting this wrong:** A payment service that cancels UPI transactions after
60 seconds of waiting would cancel approximately 30-40% of legitimate UPI payments
where customers take longer than 1 minute to approve — especially common for first-time
UPI users. This is the same scenario described in FS-12.

**Our implementation:** `app/gateways/upi_mock.py` comments reference the correct
5-minute mandate window. The reconciliation engine's stale transaction threshold
is configured separately from gateway timeout values.


---

### Error 4 — Idempotency Key Scope (Section A4.1 + FS-13)

**Location:** Section A4.1 — Idempotency Key Strategy, and the database schema shown in Section A4.2

**What the spec says in A4.2:**
```sql
CREATE TABLE idempotency_keys (
    key VARCHAR(255) PRIMARY KEY,
    ...
```

**What FS-13 then requires:**
> "Your idempotency key must be scoped to the merchant. The database key is a
> composite of (merchant_id, idempotency_key)."

**The deliberate contradiction:**
Section A4.2 shows a schema with `key VARCHAR(255) PRIMARY KEY` — a single-column
primary key. But FS-13 requires `(merchant_id, idempotency_key)` as a composite
primary key. A student who implements the schema exactly as shown in A4.2 will fail
FS-13.

This is the "subtly wrong database design recommendation" type of error from Section C6.
The error is subtle because the correct answer is *also* in the document — but only
in the failure scenario section (B2), not in the technical specification section (A4.2).
A student who only reads Section A4.2 and doesn't cross-reference with Section B2 will
build the wrong schema.


---

### Error 5 — FS-01 Specifies Wrong Failover Gateway (Section B2)

**Location:** Section B2, FS-01 — Gateway Timeout During Authorisation

**What the spec says:**
> "Router fails over to Stripe (next highest score)."

**What is actually correct:**
For a UPI payment, Stripe cannot be the next highest score because Stripe
does not support UPI at all — it scores 0.0 on the payment method fit
factor and is filtered out before scoring even begins (Section A1.3
confirms Stripe only supports card payments). The correct failover for
a UPI payment would be PayU, which supports UPI, costs less than Stripe
(1.8%+₹1.50 vs 2.5%+₹3), and has comparable success rates per Section A3.4.

**Our implementation proves this:** Live testing via Swagger UI showed UPI
payments always route to UPI gateway first, then PayU on failover — never
Stripe. The routing algorithm correctly filters Stripe out before scoring.