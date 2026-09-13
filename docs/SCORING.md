# Scoring model

This document publishes, verbatim, every formula and weight used by
`jury/engines/scoring.py` and `jury/engines/conflict.py` to turn evidence into
an Evidence Confidence score, an assumption status, and a verdict. It exists so
the numbers are defensible: a reader can check the code against this document
line by line, and argue with the weights on their own terms.

## 1. Source-tier weights

Every evidence item is assigned a source tier by the chair that gathered it.
Tier weight scales how much that item counts toward `raw_signal` (§3).

| Tier | Weight | Description |
|------|--------|-------------|
| 1    | 1.00   | Highest-trust primary source |
| 2    | 0.80   | Reputable secondary source |
| 3    | 0.55   | Weaker secondary source |
| 4    | 0.30   | Forum / anecdotal source |

A tier-5 item does not exist in this model: a model prior is not evidence and
is never scorable.

### 1.1 Tier-4 willingness-to-pay override

Stated purchase intent is known-unreliable, so a tier-4 forum anecdote about a
willingness-to-pay variable is discounted further than the base tier-4 weight:

| Variable(s) | Overridden tier-4 weight |
|-------------|--------------------------|
| `price_monthly`, `take_rate`, any variable named `wtp_*` | 0.15 |

This override only ever **narrows** tier-4 influence. It never widens it, and
it never applies to any other tier.

## 2. Strength formula

For an assumption with evidence items `i`, each carrying a tier, a per-item
confidence, and a direction (`supports` / `refutes`):

```
raw_signal = Σ (tier_weight(i) * confidence(i) * sign(i))
             where sign(i) = +1 if supports, -1 if refutes

strength = tanh(|raw_signal| / 2)
```

`strength` is bounded to `[0, 1)` and has diminishing returns: each additional
corroborating item adds less than the last. Independent corroboration is
meaningful here because deduplication guarantees the items come from distinct
sources — the same source cited twice does not count twice.

## 3. Status table

An assumption's status is derived from `strength`, `raw_signal`, and whether it
carries an unresolved conflict:

| Condition | Status |
|-----------|--------|
| Has an unresolved conflict | `contested` |
| No evidence items | `no_evidence` |
| `strength < 0.35` | `uncertain` |
| `strength >= 0.35` and `raw_signal > 0` | `supported` |
| `strength >= 0.35` and `raw_signal <= 0` | `refuted` |

An unresolved conflict dominates every other outcome: disagreement is a reason
to know less, not a reason to pick a side.

## 4. Evidence Confidence

Evidence Confidence is a 0–100 score with four published components, always
rendered alongside the total so the number is never presented without its
decomposition:

| Component | Weight | Meaning |
|-----------|--------|---------|
| `coverage` | 0.30 | Weighted fraction of the archetype's required assumption classes that carry at least one evidence item |
| `mean_strength` | 0.30 | Mean `strength` (§2) across the archetype's blocking/high-criticality assumptions |
| `contradiction` | 0.20 | Fraction of investigated blocking/high assumptions with an unresolved conflict (inverted: less contradiction scores higher) |
| `open_critical` | 0.20 | Fraction of blocking/high assumptions still in an open status — `no_evidence` or `uncertain` (inverted: fewer open items scores higher) |

```
total = 100 * ( 0.30 * coverage
              + 0.30 * mean_strength
              + 0.20 * (1 - contradiction)
              + 0.20 * (1 - open_critical) )
```

**The 0.30 / 0.30 / 0.20 / 0.20 split was chosen by judgement, not fitted to
data. It is published here so that it can be argued with.**

A record with zero assumptions gathered scores 0 on every component rather
than vacuously scoring "perfect" on `contradiction` and `open_critical` — a
record where nothing was investigated must not receive credit for having
found nothing wrong.

## 5. Verdict gate

The Jury's decision (`PROCEED` / `PIVOT` / `STOP` / `HUNG_JURY`) is gated by
Evidence Confidence and coverage, and is evaluated only after evidence
sufficiency is established. Below the gate, `PROCEED` and `STOP` are
structurally unreachable — the only possible output is `HUNG_JURY`.

The gate fires `HUNG_JURY`, in order, if:

1. `coverage` or `confidence` is not a finite number.
2. `coverage < 0.70`.
3. The archetype has no blocking-criticality assumptions at all (an empty
   blocking set must not vacuously pass).
4. Any blocking assumption is still `no_evidence` or `uncertain`.
5. `evidence_confidence < 45.0`.

Past the gate:

- If any blocking assumption is `refuted` and there is no viable adjacent
  pivot: **STOP**.
- Else if any blocking/high assumption is `refuted` and there is a viable
  adjacent pivot: **PIVOT**.
- Else if every blocking assumption is `supported`, no blocking/high
  assumption is `refuted`, the economics are viable, and there are zero
  unresolved critical conflicts: **PROCEED**.
- Otherwise: **PIVOT** (past the gate, but not clean enough for PROCEED, and
  nothing refuted to act on).

A `STOP` on thin evidence is exactly as irresponsible as a `PROCEED` on thin
evidence; the gate makes both structurally impossible below threshold.

## 6. Conflict rules R1–R5

Conflict detection is fully deterministic — no LLM is involved anywhere in
this module.

| Rule | Trigger | Threshold | Cross-examination |
|------|---------|-----------|--------------------|
| **R1** | Two evidence items, tier ≤ 2 each, opposing directions (`supports` vs `refutes`), overlapping scope | n/a | Only if the assumption's criticality is `blocking` or `high` |
| **R2** | Two numeric evidence items for the same variable, overlapping scope, whose value intervals diverge | **> ±10%** relative to the nearer interval boundary | Only if the assumption's criticality is `blocking` or `high` |
| **R3** | A founder-asserted value diverges from a matching evidence item covering the founder's target scope | **> 25%** relative divergence: `abs(asserted - evidence) / abs(evidence) > 0.25` | **Always** — R3 always triggers cross-examination, regardless of criticality |
| **R4** | A `blocking`/`high`/`medium` criticality assumption has zero evidence items | n/a | Never — silence is reported, and it feeds the confidence gate, but it does not itself trigger cross-examination |
| **R5** | Evidence exists for an assumption, but none of it covers the founder's target scope | n/a | Never — this is reported as a scope gap, not a contradiction |

R1 and R2 use the `±10%` tolerance band (`VALUE_TOLERANCE = 0.10`); values
whose intervals overlap never conflict regardless of band width. R3 uses the
`>25%` founder-divergence threshold (`FOUNDER_DIVERGENCE = 0.25`). Both
constants are published here, exactly as defined in `jury/engines/conflict.py`.

## 7. Provenance

This document is generated from, and must be kept in lockstep with:

- `jury/engines/scoring.py` (tiers, strength, status, confidence, gate)
- `jury/engines/conflict.py` (R1–R5, `VALUE_TOLERANCE`, `FOUNDER_DIVERGENCE`)

If either module changes a published number, this document changes in the
same commit.
