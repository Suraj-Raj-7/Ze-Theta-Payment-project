# Routing Algorithm

> This document explains how PayFlow decides which payment gateway
> to use for each transaction, and how it handles gateway failures.

---

## The Problem This Solves

PayFlow has 4 gateways: Razorpay, Stripe, PayU, UPI.

For any given payment, it needs to answer: **which gateway should I use?**

The answer depends on multiple factors simultaneously:
- Which gateways even support this payment method?
- Which gateway has been most reliable recently?
- Which gateway is fastest?
- Which gateway is cheapest?
- Is any gateway currently failing (circuit breaker open)?

The routing algorithm combines all of these into a single score per
gateway, picks the highest scorer, and falls back to the next best
if that one fails.

---

## Step 1 — Hard Filter (Payment Method Support)

Before scoring anything, gateways that don't support the requested
payment method are eliminated entirely:

```python
GATEWAY_METHOD_SUPPORT = {
    "razorpay": {"upi", "card", "netbanking"},
    "stripe":   {"card"},           # stripe only supports cards
    "payu":     {"upi", "card", "netbanking"},
    "upi":      {"upi"},            # UPI gateway only supports UPI
}
```

Example: A UPI payment eliminates Stripe immediately. No score is
even calculated for it. This is a hard filter, not a penalty.

---

## Step 2 — Score Each Remaining Gateway

Each remaining gateway gets a score between 0 and 1 using this formula:

```
Score = (success_rate_score × 0.35)
      + (latency_score      × 0.20)
      + (cost_score         × 0.20)
      + (health_score       × 0.15)
      + (fit_score          × 0.10)
```

The weights (0.35, 0.20, etc.) come from the Ze Theta specification
(Section A3.1). Higher weight = more important factor.

### Factor 1: Success Rate (weight: 0.35 — most important)

Taken directly from the health monitor's sliding window of the last
100 requests to that gateway.

```
success_rate_score = gateway.success_rate  # 0.0 to 1.0
```

A gateway that succeeded on 95 of its last 100 requests scores 0.95.
A gateway that succeeded on 50 scores 0.50.

This is the highest-weighted factor because a gateway that keeps
failing is useless regardless of how cheap or fast it is.

### Factor 2: Latency (weight: 0.20)

Uses p95 latency — the latency that 95% of requests complete within.
This is more meaningful than average latency because it captures
occasional slowdowns that averages hide.

Lower latency = higher score. Normalised across all gateways:

```
latency_score = 1 - ((gateway_latency - min_latency) / latency_range)
```

The gateway with the lowest latency gets score 1.0.
The gateway with the highest latency gets score 0.0.
Others are proportionally distributed between them.

### Factor 3: Cost (weight: 0.20)

Each gateway has a percentage fee plus a fixed fee per transaction:

```python
GATEWAY_COST = {
    "razorpay": {"percentage": 2.0, "fixed_paise": 200},  # 2% + ₹2
    "stripe":   {"percentage": 2.5, "fixed_paise": 300},  # 2.5% + ₹3
    "payu":     {"percentage": 1.8, "fixed_paise": 150},  # 1.8% + ₹1.50
    "upi":      {"percentage": 0.0, "fixed_paise": 0},    # free
}
```

Total cost for a gateway = `(amount × percentage / 100) + fixed_paise`

Lower cost = higher score. Normalised the same way as latency:

```
cost_score = 1 - ((gateway_cost - min_cost) / cost_range)
```

UPI is always cheapest (0 fees), so for UPI payments, UPI gateway
gets 1.0 on this factor. This is one reason UPI payments almost
always route to the UPI gateway.

### Factor 4: Health / Circuit Breaker State (weight: 0.15)

```python
health_score = {
    "CLOSED":    1.0,   # normal, fully healthy
    "HALF_OPEN": 0.5,   # recovering, being tested
    "OPEN":      0.0,   # failing, don't use
}
```

A gateway with an OPEN circuit breaker gets 0.0 here AND is skipped
entirely by the `can_attempt()` check in the failover loop (see below).
The score of 0.0 is a belt-and-suspenders precaution.

### Factor 5: Fit Score (weight: 0.10)

After the hard filter in Step 1, every remaining gateway supports
the payment method — so this is always 1.0 for surviving gateways.

It exists in the formula for completeness and future extensibility
(e.g. scoring partial support differently from full support).

---

## Step 3 — Sort and Select

All scored gateways are sorted highest score first. The router picks
the first one whose circuit breaker allows an attempt:

```python
for candidate in sorted_by_score:
    if circuit_breaker.can_attempt(candidate.gateway):
        return candidate.gateway  # this is the winner
```

---

## Step 4 — Failover (If First Gateway Fails)

`execute_authorize_with_failover()` wraps the above with retry logic:

```
Attempt 1: Pick best gateway → try it → SUCCESS → done
                                      → FAIL → record failure, continue

Attempt 2: Pick next best (excluding already-tried) → try it → SUCCESS → done
                                                               → FAIL → continue

Attempt 3: Pick next best → try it → return result (success or final failure)
```

Each failure is recorded in both the health monitor (lowers success
rate) and the circuit breaker (increments failure count). So a gateway
that fails in a failover scenario becomes less likely to be chosen
first on the next payment.

**Maximum attempts: 3** — to prevent infinite loops if all gateways
are failing simultaneously.

---

## Example: A ₹450 UPI Payment

Amount: 45000 paise. Payment method: UPI.

**Step 1 — Hard filter:**
- Razorpay: supports UPI ✓
- Stripe: does NOT support UPI ✗ → eliminated
- PayU: supports UPI ✓
- UPI: supports UPI ✓

**Step 2 — Score the 3 remaining (assuming fresh system, no history):**

Default health snapshot (no requests yet): success_rate=1.0, latency=300ms

Cost calculation:
- Razorpay: (45000 × 2.0 / 100) + 200 = 900 + 200 = 1100 paise
- PayU:     (45000 × 1.8 / 100) + 150 = 810 + 150 = 960 paise
- UPI:      (45000 × 0.0 / 100) + 0   = 0 paise  ← cheapest

Normalised cost scores (lower cost = higher score):
- UPI: 1.0 (cheapest)
- PayU: ~0.13
- Razorpay: 0.0 (most expensive of the three)

With equal success rates and latencies, cost becomes the tiebreaker.
**Result: UPI gateway selected first.**

This matches what was observed in live testing (Phase 5): a UPI
payment through the Swagger UI always routed to the UPI gateway.

---

## Where This Lives in the Code

| File | What it does |
|---|---|
| `app/services/router.py` | `score_gateways()`, `select_gateway()`, `execute_authorize_with_failover()` |
| `app/services/health_monitor.py` | Tracks success rate and latency per gateway (sliding window of 100 requests) |
| `app/services/circuit_breaker.py` | Tracks CLOSED/OPEN/HALF_OPEN state per gateway |
| `tests/test_routing.py` | ~20 tests covering scoring, failover, and circuit breaker integration |
