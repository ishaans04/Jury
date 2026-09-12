# Phase 1 — Deterministic Engines

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **PRD:** §9 (scoring and gating), §12.2 (scope overlap), §16.3 (conflict rules), §16.5 (economics), §16.6 (experiments), §16.8 (diff), §19.2 (component evals)

**Phase goal:** Every engine that decides anything, implemented as pure functions over typed inputs, with zero network and zero credentials.

**Why this is the highest-value phase:** PRD §23.1 slide 8 — *"Slide 8's strongest line is the one about where AI is not used."* Everything in this phase is deliberately deterministic, and PRD §19.2 requires these components to score **100%**: *"Deterministic components must score 100%. That is the point of making them deterministic."*

**Hard boundary (spec §6):** `jury/engines/` imports **only** `jury/schemas/`. No HTTP client, no database handle, no LLM call, no `settings`. Any engine that needs data receives it as an argument. A test that needs a database is a sign the boundary broke.

**Gate:** `uv run pytest tests/engines -q` green with every PRD §19.2 deterministic row at 100%.

---

## File structure

| Path | Responsibility | Pure? |
|---|---|---|
| `jury/engines/scope.py` | Scope overlap and superset rules (PRD §12.2) | yes |
| `jury/engines/dedup.py` | `dedup_hash` derivation (P10) | yes |
| `jury/engines/scoring.py` | Tier weights, strength, status, Evidence Confidence, verdict gate (PRD §9) | yes |
| `jury/engines/conflict.py` | R1–R5 (PRD §16.3) | yes |
| `jury/engines/economics/templates.py` | Four typed archetype templates | yes |
| `jury/engines/economics/solver.py` | `brentq` breakpoints + elasticity (PRD §16.5) | yes |
| `jury/engines/experiments.py` | Sensitivity → method mapping → `criterion_spec` (PRD §16.6) | yes |
| `jury/engines/criterion.py` | Kill-criterion evaluation | yes |
| `jury/engines/diff.py` | Typed ledger diff + causal sentence (PRD §16.8) | yes |
| `tests/engines/test_scope.py` | Fixture matrix over the enums — must be 100% | |
| `tests/engines/test_dedup.py` | | |
| `tests/engines/test_scoring.py` | Hand-computed fixtures | |
| `tests/engines/test_gate.py` | **Unreachability** proof for PROCEED/STOP | |
| `tests/engines/test_conflict.py` | Synthetic fixtures, known conflicts and known scope gaps — 100% | |
| `tests/engines/test_economics.py` | Hand-computed fixtures — **exact** agreement | |
| `tests/engines/test_experiments.py` | | |
| `tests/engines/test_criterion.py` | 100% | |
| `tests/engines/test_diff.py` | | |

---

### Task 1.1: Scope overlap

**Files:**
- Create: `apps/api/jury/engines/__init__.py`, `apps/api/jury/engines/scope.py`
- Test: `apps/api/tests/engines/test_scope.py`

**Interfaces:**
- Consumes: `jury.schemas.scope.Scope`, `jury.schemas.enums.{Geo,Segment,Tier}`
- Produces:
  - `scopes_overlap(a: Scope, b: Scope) -> bool`
  - `covers_target(evidence: Scope, target: Scope) -> bool`

**The rule (PRD §12.2, verbatim):** *"two scopes overlap if every populated field either matches or one side is a superset (`GLOBAL` supersets any geo; a null tier supersets all tiers)."*

**Why it must be exact:** this function is the difference between a real contradiction and a fake one. PRD §12.1: without it *"the conflict engine would flag ₹149 US-SMB against ₹500 IN-enterprise as a contradiction."*

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_scope.py`:
```python
import itertools

import pytest

from jury.engines.scope import covers_target, scopes_overlap
from jury.schemas.enums import Geo, Segment, Tier
from jury.schemas.scope import Scope


def s(geo="IN", segment="smb", tier=None, period=None) -> Scope:
    return Scope(geo=geo, segment=segment, tier=tier, period=period)


def test_identical_scopes_overlap():
    assert scopes_overlap(s(), s()) is True


def test_different_geo_does_not_overlap():
    """The exact false positive PRD §12.1 names."""
    assert scopes_overlap(s(geo="US", segment="smb"), s(geo="IN", segment="enterprise")) is False


def test_global_supersets_any_geo():
    assert scopes_overlap(s(geo="GLOBAL"), s(geo="IN")) is True
    assert scopes_overlap(s(geo="IN"), s(geo="GLOBAL")) is True


def test_global_vs_global_overlaps():
    assert scopes_overlap(s(geo="GLOBAL"), s(geo="GLOBAL")) is True


def test_null_tier_supersets_all_tiers():
    assert scopes_overlap(s(tier=None), s(tier="premium")) is True
    assert scopes_overlap(s(tier="premium"), s(tier=None)) is True


def test_differing_populated_tiers_do_not_overlap():
    assert scopes_overlap(s(tier="entry"), s(tier="premium")) is False


def test_differing_segments_do_not_overlap():
    assert scopes_overlap(s(segment="smb"), s(segment="enterprise")) is False


def test_null_period_supersets_any_period():
    assert scopes_overlap(s(period=None), s(period="2026")) is True


def test_differing_periods_do_not_overlap():
    assert scopes_overlap(s(period="2024"), s(period="2026")) is False


def test_quarter_within_year_overlaps():
    """2026-Q1 is inside 2026. Treating them as disjoint would invent conflicts."""
    assert scopes_overlap(s(period="2026"), s(period="2026-Q1")) is True
    assert scopes_overlap(s(period="2026-Q1"), s(period="2026")) is True


def test_different_quarters_same_year_do_not_overlap():
    assert scopes_overlap(s(period="2026-Q1"), s(period="2026-Q3")) is False


def test_overlap_is_symmetric_across_the_whole_enum_matrix():
    """PRD §19.2 requires 100% on a fixture matrix over the enums."""
    scopes = [
        Scope(geo=g, segment=sg, tier=t, period=p)
        for g, sg, t, p in itertools.product(
            [Geo.IN, Geo.US, Geo.GLOBAL],
            [Segment.SMB, Segment.ENTERPRISE],
            [None, Tier.ENTRY, Tier.PREMIUM],
            [None, "2026", "2026-Q1"],
        )
    ]
    assert len(scopes) == 54
    for a, b in itertools.product(scopes, scopes):
        assert scopes_overlap(a, b) == scopes_overlap(b, a), (a, b)


def test_overlap_is_reflexive_across_the_matrix():
    for g, sg, t, p in itertools.product(list(Geo), list(Segment),
                                         [None, *list(Tier)], [None, "2026"]):
        sc = Scope(geo=g, segment=sg, tier=t, period=p)
        assert scopes_overlap(sc, sc) is True


def test_covers_target_is_directional_not_symmetric():
    """R5 asks whether EVIDENCE covers the FOUNDER'S TARGET. GLOBAL evidence
    covers an IN target; IN evidence does not cover a GLOBAL target."""
    assert covers_target(evidence=s(geo="GLOBAL"), target=s(geo="IN")) is True
    assert covers_target(evidence=s(geo="IN"), target=s(geo="GLOBAL")) is False


def test_covers_target_null_evidence_tier_covers_specific_target_tier():
    assert covers_target(evidence=s(tier=None), target=s(tier="entry")) is True
    assert covers_target(evidence=s(tier="entry"), target=s(tier=None)) is False
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_scope.py -v
```
Expected: FAIL — `No module named 'jury.engines.scope'`.

- [ ] **Step 3: Write the implementation**

`apps/api/jury/engines/scope.py`:
```python
"""Scope comparison. PRD §12.2.

Overlap rule: two scopes overlap if every populated field either matches or one
side is a superset. GLOBAL supersets any geo; a null tier supersets all tiers.

This module is pure: it imports only schemas and performs no I/O.
"""
from jury.schemas.enums import Geo
from jury.schemas.scope import Scope


def _geo_superset_of(wide: Geo, narrow: Geo) -> bool:
    return wide is Geo.GLOBAL or wide is narrow


def _period_superset_of(wide: str | None, narrow: str | None) -> bool:
    """None supersets everything. A year supersets its own quarters."""
    if wide is None:
        return True
    if narrow is None:
        return False
    if wide == narrow:
        return True
    # "2026" supersets "2026-Q1"; the reverse is not true.
    return len(wide) == 4 and narrow.startswith(wide + "-Q")


def _one_way_covers(wide: Scope, narrow: Scope) -> bool:
    """True if `wide` is at least as broad as `narrow` on every field."""
    if not _geo_superset_of(wide.geo, narrow.geo):
        return False
    if wide.segment is not narrow.segment:
        return False
    if wide.tier is not None and wide.tier is not narrow.tier:
        return False
    return _period_superset_of(wide.period, narrow.period)


def scopes_overlap(a: Scope, b: Scope) -> bool:
    """Symmetric. Two claims are comparable only if their scopes overlap.

    Without this gate the conflict engine would report Rs 149 US-SMB against
    Rs 500 IN-enterprise as a contradiction (PRD §12.1).
    """
    return _one_way_covers(a, b) or _one_way_covers(b, a)


def covers_target(evidence: Scope, target: Scope) -> bool:
    """Directional: does this evidence apply to the founder's target scope?

    Drives R5 (scope_gap) — evidence exists, but none of it covers your target,
    which PRD §12.1 calls "its own valuable finding".
    """
    return _one_way_covers(evidence, target)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_scope.py -v
```
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/engines apps/api/tests/engines/test_scope.py
git commit -m "feat(engines): scope overlap and directional target coverage"
```

---

### Task 1.2: Dedup hash

**Files:**
- Create: `apps/api/jury/engines/dedup.py`
- Test: `apps/api/tests/engines/test_dedup.py`

**Interfaces:**
- Produces:
  - `canonicalise_url(url: str) -> str`
  - `dedup_hash(canonical_url: str, variable: str | None, scope: Scope) -> str`

**Rule (PRD §12.1):** `dedup_hash = sha256(canonical_url ‖ variable ‖ scope_geo ‖ scope_segment ‖ scope_tier)`. Note `scope_period` is deliberately **excluded** — PRD §12.1 lists exactly five components.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_dedup.py`:
```python
from jury.engines.dedup import canonicalise_url, dedup_hash
from jury.schemas.scope import Scope


def s(**kw) -> Scope:
    return Scope(**{"geo": "IN", "segment": "smb", **kw})


def test_same_source_variable_and_scope_hash_identically():
    """P10: two chairs finding the same pricing page cannot inflate confidence twice."""
    a = dedup_hash("https://x.test/pricing", "price_monthly", s(tier="entry"))
    b = dedup_hash("https://x.test/pricing", "price_monthly", s(tier="entry"))
    assert a == b


def test_different_variable_hashes_differently():
    a = dedup_hash("https://x.test/pricing", "price_monthly", s())
    b = dedup_hash("https://x.test/pricing", "churn_monthly", s())
    assert a != b


def test_different_scope_hashes_differently():
    a = dedup_hash("https://x.test/p", "price_monthly", s(geo="IN"))
    b = dedup_hash("https://x.test/p", "price_monthly", s(geo="US"))
    assert a != b


def test_period_is_excluded_from_the_hash():
    """PRD §12.1 lists exactly five components; period is not one of them."""
    a = dedup_hash("https://x.test/p", "price_monthly", s(period="2025"))
    b = dedup_hash("https://x.test/p", "price_monthly", s(period="2026"))
    assert a == b


def test_null_variable_is_stable():
    a = dedup_hash("https://x.test/p", None, s())
    b = dedup_hash("https://x.test/p", None, s())
    assert a == b and len(a) == 64


def test_tracking_params_are_stripped():
    assert (canonicalise_url("https://x.test/p?utm_source=twitter&utm_medium=x")
            == "https://x.test/p")


def test_real_query_params_are_kept_and_sorted():
    assert (canonicalise_url("https://x.test/p?b=2&a=1")
            == "https://x.test/p?a=1&b=2")


def test_fragment_and_trailing_slash_stripped():
    assert canonicalise_url("https://x.test/p/#pricing") == "https://x.test/p"


def test_host_is_lowercased_and_www_stripped():
    assert canonicalise_url("https://WWW.X.test/P") == "https://x.test/P"


def test_default_ports_are_stripped():
    assert canonicalise_url("https://x.test:443/p") == "https://x.test/p"


def test_canonicalisation_makes_dedup_catch_tracked_duplicates():
    """The whole point: a URL shared with tracking params is the same source."""
    a = dedup_hash(canonicalise_url("https://x.test/pricing?utm_campaign=a"), "price_monthly", s())
    b = dedup_hash(canonicalise_url("https://x.test/pricing"), "price_monthly", s())
    assert a == b
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_dedup.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

`apps/api/jury/engines/dedup.py`:
```python
"""Deduplication. P10: the same source found twice never raises confidence.

PRD §12.1: dedup_hash = sha256(canonical_url || variable || scope_geo
                               || scope_segment || scope_tier)
"""
import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jury.schemas.scope import Scope

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset({
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer",
    "igshid", "si", "spm", "_hsenc", "_hsmi", "yclid", "twclid",
})
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def canonicalise_url(url: str) -> str:
    """Strip tracking parameters, fragments and trailing slashes before hashing.

    PRD §16.1: "Canonicalisation strips tracking parameters, fragments, and
    trailing slashes before hashing."
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()

    host = parts.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if parts.port and str(parts.port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"

    path = parts.path.rstrip("/")

    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_KEYS
        and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(kept))

    return urlunsplit((scheme, netloc, path, query, ""))


def dedup_hash(canonical_url: str, variable: str | None, scope: Scope) -> str:
    """Five components exactly, per PRD §12.1. Period is deliberately excluded."""
    payload = "\x1f".join([
        canonical_url,
        variable or "",
        scope.geo.value,
        scope.segment.value,
        scope.tier.value if scope.tier else "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_dedup.py -v
```
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/engines/dedup.py apps/api/tests/engines/test_dedup.py
git commit -m "feat(engines): url canonicalisation and dedup hash"
```

---

### Task 1.3: Scoring — strength, status, Evidence Confidence

**Files:**
- Create: `apps/api/jury/engines/scoring.py`
- Test: `apps/api/tests/engines/test_scoring.py`

**Interfaces:**
- Consumes: `Scope`, enums
- Produces:
  - `TIER_WEIGHTS: dict[int, float]` = `{1: 1.00, 2: 0.80, 3: 0.55, 4: 0.30}`
  - `CONFIDENCE_WEIGHTS: dict[str, float]` = `{"coverage": .30, "mean_strength": .30, "contradiction": .20, "open_critical": .20}`
  - `tier_weight(tier: int, variable: str | None = None) -> float`
  - `EvidenceLike` dataclass: `tier: int`, `confidence: float`, `direction: Direction`, `variable: str | None`
  - `AssumptionLike` dataclass: `id: str`, `class_key: str | None`, `criticality: Criticality`, `evidence: list[EvidenceLike]`, `has_unresolved_conflict: bool`
  - `strength(items: list[EvidenceLike]) -> float`
  - `assign_status(items, has_unresolved_conflict: bool) -> AssumptionStatus`
  - `coverage(classes: list[tuple[str, float]], assumptions: list[AssumptionLike]) -> float`
  - `evidence_confidence(...) -> tuple[float, ConfidenceComponents]`

**Formulas (PRD §9.2, §9.3) — copy exactly:**
```
support(a)  = Σ tier_weight(i) × confidence(i)   for direction = supports
refute(a)   = Σ tier_weight(i) × confidence(i)   for direction = refutes
raw(a)      = support(a) − refute(a)
strength(a) = tanh(|raw(a)| / 2)
```

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_scoring.py`:
```python
import math

import pytest

from jury.engines.scoring import (
    CONFIDENCE_WEIGHTS, TIER_WEIGHTS, AssumptionLike, EvidenceLike,
    assign_status, coverage, evidence_confidence, strength, tier_weight,
)
from jury.schemas.enums import AssumptionStatus, Criticality, Direction


def ev(tier=1, conf=1.0, direction="supports", variable=None) -> EvidenceLike:
    return EvidenceLike(tier=tier, confidence=conf,
                        direction=Direction(direction), variable=variable)


# ── tier weights: PRD §9.1 exact values ──────────────────────────────────────
def test_tier_weights_are_the_published_values():
    assert TIER_WEIGHTS == {1: 1.00, 2: 0.80, 3: 0.55, 4: 0.30}


def test_tier_five_has_no_weight_and_is_not_persistable():
    with pytest.raises(KeyError):
        _ = TIER_WEIGHTS[5]


def test_tier4_wtp_variables_are_discounted(): 
    """Spec §26.4: stated willingness to pay is notoriously unreliable."""
    assert tier_weight(4, "price_monthly") == 0.15
    assert tier_weight(4, "wtp_annual") == 0.15
    assert tier_weight(4, "take_rate") == 0.15


def test_tier4_other_variables_keep_the_baseline():
    assert tier_weight(4, "delivery_cost") == 0.30
    assert tier_weight(4, None) == 0.30


def test_the_override_never_widens_tier4_influence():
    for v in ("price_monthly", "wtp_x", "take_rate", "anything", None):
        assert tier_weight(4, v) <= 0.30


def test_higher_tiers_are_unaffected_by_the_wtp_override():
    assert tier_weight(1, "price_monthly") == 1.00
    assert tier_weight(2, "price_monthly") == 0.80


# ── strength: PRD §9.2 ───────────────────────────────────────────────────────
def test_no_evidence_is_zero_strength():
    assert strength([]) == 0.0


def test_single_tier1_support_matches_hand_computation():
    # raw = 1.00 * 1.0 = 1.0 ; tanh(0.5)
    assert strength([ev(1, 1.0)]) == pytest.approx(math.tanh(0.5))


def test_opposing_equal_evidence_cancels_to_zero():
    assert strength([ev(1, 1.0, "supports"), ev(1, 1.0, "refutes")]) == pytest.approx(0.0)


def test_strength_uses_absolute_raw_so_refutation_is_as_strong_as_support():
    a = strength([ev(1, 1.0, "supports"), ev(1, 1.0, "supports")])
    b = strength([ev(1, 1.0, "refutes"), ev(1, 1.0, "refutes")])
    assert a == pytest.approx(b)


def test_independent_corroboration_raises_strength_with_diminishing_returns():
    """P10 guarantees distinct sources, so more items legitimately raise strength —
    but tanh means the fourth source adds less than the second."""
    one, two, three = (strength([ev(1, 1.0)] * n) for n in (1, 2, 3))
    assert one < two < three
    assert (two - one) > (three - two)


def test_strength_is_bounded_to_unit_interval():
    assert 0.0 <= strength([ev(1, 1.0)] * 50) <= 1.0


def test_mixed_tiers_match_hand_computation():
    # raw = (1.00*1.0) + (0.55*0.8) - (0.30*0.5) = 1.0 + 0.44 - 0.15 = 1.29
    items = [ev(1, 1.0, "supports"), ev(3, 0.8, "supports"), ev(4, 0.5, "refutes")]
    assert strength(items) == pytest.approx(math.tanh(1.29 / 2))


# ── status assignment: PRD §9.2 table ────────────────────────────────────────
def test_zero_items_is_no_evidence():
    assert assign_status([], False) is AssumptionStatus.NO_EVIDENCE


def test_weak_evidence_is_uncertain():
    # tier 4 non-wtp, low confidence: raw = 0.30*0.2 = 0.06, tanh(0.03) ~ 0.03 < 0.35
    assert assign_status([ev(4, 0.2)], False) is AssumptionStatus.UNCERTAIN


def test_strong_positive_is_supported():
    assert assign_status([ev(1, 1.0), ev(1, 1.0)], False) is AssumptionStatus.SUPPORTED


def test_strong_negative_is_refuted():
    items = [ev(1, 1.0, "refutes"), ev(1, 1.0, "refutes")]
    assert assign_status(items, False) is AssumptionStatus.REFUTED


def test_unresolved_conflict_beats_every_other_status():
    """PRD §9.2: 'unresolved conflict present' -> contested, whatever the arithmetic says."""
    assert assign_status([ev(1, 1.0), ev(1, 1.0)], True) is AssumptionStatus.CONTESTED
    assert assign_status([], True) is AssumptionStatus.CONTESTED


def test_status_boundary_is_exactly_0_35():
    """strength >= 0.35 flips uncertain -> supported. Verify the boundary is inclusive."""
    # tanh(raw/2) = 0.35  ->  raw = 2*atanh(0.35)
    raw = 2 * math.atanh(0.35)
    items = [ev(1, raw)]          # tier 1 weight 1.0, so raw == confidence
    assert strength(items) == pytest.approx(0.35)
    assert assign_status(items, False) is AssumptionStatus.SUPPORTED


# ── coverage: PRD §9.3 ───────────────────────────────────────────────────────
def asm(class_key, criticality="blocking", n_evidence=0, conflict=False) -> AssumptionLike:
    return AssumptionLike(id=class_key or "x", class_key=class_key,
                          criticality=Criticality(criticality),
                          evidence=[ev(1, 1.0)] * n_evidence,
                          has_unresolved_conflict=conflict)


def test_coverage_is_weighted_by_criticality_not_counted():
    classes = [("a.x", 1.0), ("a.y", 0.6), ("a.z", 0.3)]
    # only the 1.0-weight class is covered -> 1.0 / 1.9
    got = coverage(classes, [asm("a.x", n_evidence=1)])
    assert got == pytest.approx(1.0 / 1.9)


def test_a_class_needs_at_least_one_evidence_item_to_count_as_covered():
    """PRD §9.3: covered(c) = 1 if >=1 assumption in c has >=1 evidence item.
    An assumption with no evidence does NOT cover its class."""
    classes = [("a.x", 1.0)]
    assert coverage(classes, [asm("a.x", n_evidence=0)]) == 0.0
    assert coverage(classes, [asm("a.x", n_evidence=1)]) == 1.0


def test_full_coverage_is_one():
    classes = [("a.x", 1.0), ("a.y", 0.6)]
    assert coverage(classes, [asm("a.x", n_evidence=1), asm("a.y", n_evidence=1)]) == 1.0


def test_coverage_of_an_empty_denominator_is_zero_not_a_crash():
    assert coverage([], []) == 0.0


def test_unclassified_assumptions_do_not_contribute_to_coverage():
    """Coverage is measured against the external denominator only (P4)."""
    classes = [("a.x", 1.0)]
    assert coverage(classes, [asm(None, n_evidence=5)]) == 0.0


# ── evidence confidence: PRD §9.3 ────────────────────────────────────────────
def test_confidence_weights_are_the_published_split():
    assert CONFIDENCE_WEIGHTS == {"coverage": 0.30, "mean_strength": 0.30,
                                  "contradiction": 0.20, "open_critical": 0.20}


def test_weights_sum_to_one():
    assert sum(CONFIDENCE_WEIGHTS.values()) == pytest.approx(1.0)


def test_perfect_record_scores_one_hundred():
    classes = [("a.x", 1.0)]
    assumptions = [asm("a.x", "blocking", n_evidence=6)]
    total, comp = evidence_confidence(classes, assumptions, unresolved_conflicts=0)
    assert comp.coverage == 1.0
    assert comp.contradiction == 0.0
    assert comp.open_critical == 0.0
    assert total == pytest.approx(100.0, abs=0.5)


def test_empty_record_scores_zero():
    total, comp = evidence_confidence([("a.x", 1.0)], [], unresolved_conflicts=0)
    assert total == pytest.approx(0.0)
    assert comp.coverage == 0.0


def test_components_are_returned_alongside_the_total():
    """PRD §9.3: the UI always displays the four components. A number without a
    visible decomposition is not defensible."""
    _, comp = evidence_confidence([("a.x", 1.0)], [asm("a.x", n_evidence=2)],
                                  unresolved_conflicts=1)
    assert set(comp.model_dump()) == {"coverage", "mean_strength",
                                      "contradiction", "open_critical"}


def test_contradiction_is_clamped_at_one():
    """More unresolved conflicts than critical assumptions must not make the
    term negative once inverted."""
    total, comp = evidence_confidence([("a.x", 1.0)], [asm("a.x", n_evidence=1)],
                                      unresolved_conflicts=99)
    assert comp.contradiction >= 1.0
    assert total >= 0.0


def test_mean_strength_only_considers_blocking_and_high():
    """PRD §9.3: mean over assumptions where criticality in {blocking, high}."""
    classes = [("a.x", 1.0), ("a.y", 0.3)]
    strong_blocking = asm("a.x", "blocking", n_evidence=6)
    weak_low = AssumptionLike(id="y", class_key="a.y", criticality=Criticality.LOW,
                              evidence=[ev(4, 0.1)], has_unresolved_conflict=False)
    _, comp = evidence_confidence(classes, [strong_blocking, weak_low],
                                  unresolved_conflicts=0)
    assert comp.mean_strength == pytest.approx(strength(strong_blocking.evidence))


def test_open_critical_counts_no_evidence_and_uncertain():
    classes = [("a.x", 1.0), ("a.y", 1.0)]
    covered = asm("a.x", "blocking", n_evidence=6)
    bare = asm("a.y", "blocking", n_evidence=0)
    _, comp = evidence_confidence(classes, [covered, bare], unresolved_conflicts=0)
    assert comp.open_critical == pytest.approx(0.5)


def test_confidence_is_bounded_to_0_100():
    classes = [("a.x", 1.0)]
    for n in (0, 1, 3, 20):
        total, _ = evidence_confidence(classes, [asm("a.x", n_evidence=n)],
                                       unresolved_conflicts=n)
        assert 0.0 <= total <= 100.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_scoring.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

`apps/api/jury/engines/scoring.py`:
```python
"""Scoring. PRD §9, formula-for-formula.

The scoring model exists to make the numbers defensible: every input is
countable, and every weight is published in docs/SCORING.md.

Pure module. Callers pass data in; nothing here touches a database.
"""
import math
from dataclasses import dataclass, field

from jury.schemas.enums import AssumptionStatus, Criticality, Direction
from jury.schemas.verdict import ConfidenceComponents

# ── PRD §9.1, exact published values ─────────────────────────────────────────
TIER_WEIGHTS: dict[int, float] = {1: 1.00, 2: 0.80, 3: 0.55, 4: 0.30}

# Spec §26.4: tier-4 forum anecdote is discounted for variables where stated
# intent is known-unreliable. This only ever narrows tier-4 influence.
_TIER4_WTP_WEIGHT = 0.15
_TIER4_WTP_EXACT = frozenset({"price_monthly", "take_rate"})
_TIER4_WTP_PREFIXES = ("wtp_",)

# ── PRD §9.3 / spec §26.3 ────────────────────────────────────────────────────
# Chosen by judgement, not fitted to data. Published in docs/SCORING.md.
# Defined once here so the backtest can vary them without touching logic.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "coverage": 0.30,
    "mean_strength": 0.30,
    "contradiction": 0.20,
    "open_critical": 0.20,
}

STRENGTH_THRESHOLD = 0.35          # PRD §9.2 status table
_CRITICAL = frozenset({Criticality.BLOCKING, Criticality.HIGH})
_OPEN_STATUSES = frozenset({AssumptionStatus.NO_EVIDENCE, AssumptionStatus.UNCERTAIN})


@dataclass(frozen=True, slots=True)
class EvidenceLike:
    """The subset of an evidence row that scoring needs. Keeps the engine pure."""
    tier: int
    confidence: float
    direction: Direction
    variable: str | None = None


@dataclass(frozen=True, slots=True)
class AssumptionLike:
    id: str
    class_key: str | None
    criticality: Criticality
    evidence: list[EvidenceLike] = field(default_factory=list)
    has_unresolved_conflict: bool = False


def tier_weight(tier: int, variable: str | None = None) -> float:
    """Weight for one evidence item. Raises KeyError on tier 5 — a model prior
    is not evidence and must never be scorable (P1)."""
    base = TIER_WEIGHTS[tier]
    if tier == 4 and variable:
        v = variable.lower()
        if v in _TIER4_WTP_EXACT or v.startswith(_TIER4_WTP_PREFIXES):
            return _TIER4_WTP_WEIGHT
    return base


def raw_signal(items: list[EvidenceLike]) -> float:
    """support - refute, each side weighted by tier and item confidence."""
    total = 0.0
    for i in items:
        w = tier_weight(i.tier, i.variable) * i.confidence
        total += w if i.direction is Direction.SUPPORTS else -w
    return total


def strength(items: list[EvidenceLike]) -> float:
    """tanh(|raw| / 2) -> 0..1 with diminishing returns (PRD §9.2).

    Independent corroboration raises strength because dedup (P10) guarantees
    the items come from distinct sources.
    """
    if not items:
        return 0.0
    return math.tanh(abs(raw_signal(items)) / 2.0)


def assign_status(items: list[EvidenceLike],
                  has_unresolved_conflict: bool) -> AssumptionStatus:
    """PRD §9.2 status table. Unresolved conflict dominates every other outcome:
    disagreement is a reason to know less, not a reason to pick a side."""
    if has_unresolved_conflict:
        return AssumptionStatus.CONTESTED
    if not items:
        return AssumptionStatus.NO_EVIDENCE
    s = strength(items)
    if s < STRENGTH_THRESHOLD:
        return AssumptionStatus.UNCERTAIN
    return (AssumptionStatus.SUPPORTED if raw_signal(items) > 0
            else AssumptionStatus.REFUTED)


def coverage(classes: list[tuple[str, float]],
             assumptions: list[AssumptionLike]) -> float:
    """Weighted fraction of the archetype's assumption classes that carry evidence.

    PRD §9.3:
        coverage = sum(crit_weight(c) * covered(c)) / sum(crit_weight(c))
        covered(c) = 1 if >=1 assumption in c has >=1 evidence item

    P4: `classes` is the hand-seeded external denominator. Passing a
    runtime-generated list here would hollow out the whole product.
    """
    denominator = sum(w for _, w in classes)
    if denominator == 0:
        return 0.0
    with_evidence = {a.class_key for a in assumptions if a.class_key and a.evidence}
    numerator = sum(w for key, w in classes if key in with_evidence)
    return numerator / denominator


def evidence_confidence(
    classes: list[tuple[str, float]],
    assumptions: list[AssumptionLike],
    unresolved_conflicts: int,
) -> tuple[float, ConfidenceComponents]:
    """Evidence Confidence 0-100 plus its four components (PRD §9.3).

    Returns both because the UI must always render the decomposition: a number
    with a visible decomposition is defensible, one without is not.
    """
    # A record with nothing in it scores zero, not 40. Without this guard the
    # two (1 - x) penalty terms vacuously read "perfect" when there is nothing
    # to be contradicted or left open, handing 40% of the total to a record
    # where nothing was investigated.
    if not assumptions:
        return 0.0, ConfidenceComponents(coverage=0.0, mean_strength=0.0,
                                         contradiction=0.0, open_critical=0.0)

    cov = coverage(classes, assumptions)

    critical = [a for a in assumptions if a.criticality in _CRITICAL]
    mean_strength = (sum(strength(a.evidence) for a in critical) / len(critical)
                     if critical else 0.0)

    investigated_critical = [a for a in critical if a.evidence]
    if investigated_critical:
        contradiction = unresolved_conflicts / len(investigated_critical)
    else:
        # "No contradictions found" is not a clean bill of health when nothing
        # was checked. 1.0 makes (1 - min(1, contradiction)) pay zero, matching
        # how open_critical already behaves in the same situation, and keeps the
        # displayed component honest on a partial or failed run (PRD §18).

    open_count = sum(
        1 for a in critical
        if assign_status(a.evidence, a.has_unresolved_conflict) in _OPEN_STATUSES
    )
    open_critical = open_count / max(1, len(critical))

    components = ConfidenceComponents(
        coverage=cov,
        mean_strength=mean_strength,
        contradiction=contradiction,
        open_critical=open_critical,
    )

    total = 100.0 * (
        CONFIDENCE_WEIGHTS["coverage"] * cov
        + CONFIDENCE_WEIGHTS["mean_strength"] * mean_strength
        + CONFIDENCE_WEIGHTS["contradiction"] * (1.0 - min(1.0, contradiction))
        + CONFIDENCE_WEIGHTS["open_critical"] * (1.0 - open_critical)
    )
    return max(0.0, min(100.0, total)), components
```

Note on `open_critical` when there are no critical assumptions: `max(1, 0)` makes the denominator 1 and `open_count` 0, so `open_critical = 0`. That is deliberate — an archetype with no critical assumptions cannot have open ones.

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_scoring.py -v
```
Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/engines/scoring.py apps/api/tests/engines/test_scoring.py
git commit -m "feat(engines): evidence strength, status assignment and Evidence Confidence"
```

---

### Task 1.4: The verdict gate — with an unreachability proof

**Files:**
- Modify: `apps/api/jury/engines/scoring.py` (append the gate)
- Test: `apps/api/tests/engines/test_gate.py`

**Interfaces:**
- Produces:
  - `GateResult` dataclass: `decision: Decision`, `gate_triggered: str | None`
  - `apply_gate(coverage: float, assumptions: list[AssumptionLike], confidence: float, has_viable_adjacent: bool, economics_viable: bool, unresolved_critical: int) -> GateResult`

**The gate (PRD §9.4, verbatim):**
```
IF coverage < 0.70
   OR any assumption with criticality='blocking' has status in {no_evidence, uncertain}
   OR EvidenceConfidence < 45
THEN verdict = HUNG_JURY    # PROCEED and STOP are structurally unreachable
```

**Why a dedicated test file:** F12's acceptance criterion is *"gate provably prevents PROCEED/STOP below threshold"* — provably, not probably. The test brute-forces the input space.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_gate.py`:
```python
import itertools

import pytest

from jury.engines.scoring import AssumptionLike, EvidenceLike, apply_gate
from jury.schemas.enums import Criticality, Decision, Direction


def ev(direction="supports", tier=1, conf=1.0) -> EvidenceLike:
    return EvidenceLike(tier=tier, confidence=conf, direction=Direction(direction))


def blocking(status="supported") -> AssumptionLike:
    """Build a blocking assumption whose computed status is what we asked for."""
    if status == "supported":
        items = [ev("supports")] * 3
    elif status == "refuted":
        items = [ev("refutes")] * 3
    elif status == "uncertain":
        items = [ev("supports", tier=4, conf=0.1)]
    else:                                     # no_evidence
        items = []
    return AssumptionLike(id=status, class_key="a.x",
                          criticality=Criticality.BLOCKING, evidence=items)


# ── the three gate conditions ────────────────────────────────────────────────
def test_low_coverage_hangs_the_jury():
    r = apply_gate(coverage=0.69, assumptions=[blocking("supported")], confidence=90.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "coverage_below_0.70"


def test_coverage_exactly_at_threshold_does_not_hang():
    r = apply_gate(coverage=0.70, assumptions=[blocking("supported")], confidence=90.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is not Decision.HUNG_JURY


def test_blocking_assumption_with_no_evidence_hangs_the_jury():
    r = apply_gate(coverage=0.99, assumptions=[blocking("no_evidence")], confidence=99.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "blocking_assumption_unresolved"


def test_blocking_assumption_merely_uncertain_hangs_the_jury():
    r = apply_gate(coverage=0.99, assumptions=[blocking("uncertain")], confidence=99.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "blocking_assumption_unresolved"


def test_low_confidence_hangs_the_jury():
    r = apply_gate(coverage=0.99, assumptions=[blocking("supported")], confidence=44.9,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "confidence_below_45"


def test_confidence_exactly_45_does_not_hang():
    r = apply_gate(coverage=0.99, assumptions=[blocking("supported")], confidence=45.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is not Decision.HUNG_JURY


# ── the unreachability proof (F12 acceptance criterion) ──────────────────────
def test_proceed_and_stop_are_structurally_unreachable_below_threshold():
    """P5 / F12: below threshold, PROCEED and STOP must be UNREACHABLE, not unlikely.

    Brute-force every combination of the three gate conditions together with
    every downstream input that could otherwise produce PROCEED or STOP.
    """
    sub_coverages = [0.0, 0.35, 0.699]
    sub_confidences = [0.0, 20.0, 44.999]
    statuses = ["supported", "refuted", "uncertain", "no_evidence"]

    checked = 0
    for cov, conf, status, adjacent, viable, unresolved in itertools.product(
        sub_coverages, sub_confidences, statuses, [True, False], [True, False], [0, 3]
    ):
        r = apply_gate(coverage=cov, assumptions=[blocking(status)], confidence=conf,
                       has_viable_adjacent=adjacent, economics_viable=viable,
                       unresolved_critical=unresolved)
        assert r.decision is Decision.HUNG_JURY, (cov, conf, status)
        assert r.decision not in (Decision.PROCEED, Decision.STOP)
        checked += 1
    assert checked == 3 * 3 * 4 * 2 * 2 * 2   # 288 combinations


def test_any_single_failing_condition_is_sufficient_to_hang():
    """The gate is a disjunction: passing two conditions does not rescue the third."""
    ok = dict(coverage=0.99, assumptions=[blocking("supported")], confidence=99.0,
              has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert apply_gate(**ok).decision is not Decision.HUNG_JURY
    assert apply_gate(**{**ok, "coverage": 0.1}).decision is Decision.HUNG_JURY
    assert apply_gate(**{**ok, "confidence": 1.0}).decision is Decision.HUNG_JURY
    assert apply_gate(**{**ok, "assumptions": [blocking("no_evidence")]}
                      ).decision is Decision.HUNG_JURY


# ── post-gate verdict table (PRD §9.4) ───────────────────────────────────────
def test_refuted_blocking_with_no_adjacency_is_stop():
    r = apply_gate(coverage=0.9, assumptions=[blocking("refuted")], confidence=80.0,
                   has_viable_adjacent=False, economics_viable=False, unresolved_critical=0)
    assert r.decision is Decision.STOP


def test_refuted_blocking_with_a_viable_adjacency_is_pivot():
    r = apply_gate(coverage=0.9, assumptions=[blocking("refuted")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=False, unresolved_critical=0)
    assert r.decision is Decision.PIVOT


def test_all_supported_and_viable_and_unconflicted_is_proceed():
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.PROCEED


def test_unresolved_critical_conflict_blocks_proceed():
    """PRD §9.4 PROCEED requires 'no unresolved critical conflicts'."""
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=1)
    assert r.decision is not Decision.PROCEED


def test_non_viable_economics_blocks_proceed():
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=False, unresolved_critical=0)
    assert r.decision is not Decision.PROCEED


def test_gate_triggered_is_none_when_the_gate_did_not_fire():
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.gate_triggered is None


def test_high_criticality_refuted_also_permits_pivot():
    """PRD §9.4 PIVOT: '>=1 blocking OR high assumption refuted' with adjacency."""
    high_refuted = AssumptionLike(id="h", class_key="a.y", criticality=Criticality.HIGH,
                                  evidence=[ev("refutes")] * 3)
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported"), high_refuted],
                   confidence=80.0, has_viable_adjacent=True, economics_viable=True,
                   unresolved_critical=0)
    assert r.decision is Decision.PIVOT
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_gate.py -v
```
Expected: FAIL — `cannot import name 'apply_gate'`.

- [ ] **Step 3: Append the gate to `jury/engines/scoring.py`**

```python
# ── the verdict gate: PRD §9.4 ───────────────────────────────────────────────
# The Jury's decision is separate from Evidence Confidence and is gated by it.
# P5: below threshold, PROCEED and STOP are structurally unreachable.

COVERAGE_GATE = 0.70
CONFIDENCE_GATE = 45.0


@dataclass(frozen=True, slots=True)
class GateResult:
    decision: Decision
    gate_triggered: str | None


def apply_gate(
    coverage: float,
    assumptions: list[AssumptionLike],
    confidence: float,
    has_viable_adjacent: bool,
    economics_viable: bool,
    unresolved_critical: int,
) -> GateResult:
    """Return the verdict, or HUNG_JURY plus the condition that fired.

    A STOP on thin evidence is as irresponsible as a PROCEED on thin evidence,
    and the gate makes both impossible to express (PRD §9.5).
    """
    if coverage < COVERAGE_GATE:
        return GateResult(Decision.HUNG_JURY, "coverage_below_0.70")

    blocking = [a for a in assumptions if a.criticality is Criticality.BLOCKING]
    for a in blocking:
        if assign_status(a.evidence, a.has_unresolved_conflict) in _OPEN_STATUSES:
            return GateResult(Decision.HUNG_JURY, "blocking_assumption_unresolved")

    if confidence < CONFIDENCE_GATE:
        return GateResult(Decision.HUNG_JURY, "confidence_below_45")

    # Past the gate. PRD §9.4 decision table.
    statuses = {
        a.id: assign_status(a.evidence, a.has_unresolved_conflict) for a in assumptions
    }
    refuted_blocking = [a for a in blocking
                        if statuses[a.id] is AssumptionStatus.REFUTED]
    refuted_critical = [a for a in assumptions
                        if a.criticality in _CRITICAL
                        and statuses[a.id] is AssumptionStatus.REFUTED]

    if refuted_blocking and not has_viable_adjacent:
        return GateResult(Decision.STOP, None)
    if refuted_critical and has_viable_adjacent:
        return GateResult(Decision.PIVOT, None)

    all_blocking_supported = all(
        statuses[a.id] is AssumptionStatus.SUPPORTED for a in blocking
    )
    if all_blocking_supported and economics_viable and unresolved_critical == 0:
        return GateResult(Decision.PROCEED, None)

    # Past the gate but not clean enough for PROCEED, and no refutation to act on.
    return GateResult(Decision.PIVOT, None)
```

Also add `Decision` to the module's imports from `jury.schemas.enums`.

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_gate.py -v
```
Expected: 16 passed, including the 288-combination unreachability proof.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/engines/scoring.py apps/api/tests/engines/test_gate.py
git commit -m "feat(engines): verdict gate with brute-forced unreachability proof"
```

---

### Task 1.5: Conflict engine R1–R5

**Files:**
- Create: `apps/api/jury/engines/conflict.py`
- Test: `apps/api/tests/engines/test_conflict.py`

**Interfaces:**
- Produces:
  - `ConflictInput` dataclass: `assumption`, `evidence: list[EvidenceForConflict]`, `target_scope: Scope`
  - `EvidenceForConflict` dataclass: `id`, `chair`, `direction`, `variable`, `value_num`, `value_min`, `value_max`, `tier`, `scope`
  - `AssumptionForConflict` dataclass: `id`, `origin`, `criticality`, `asserted_variable`, `asserted_value`, `target_scope_field`
  - `DetectedConflict` dataclass: `assumption_id`, `kind`, `rule`, `left_ref`, `right_ref`, `severity`, `triggers_cross_exam`
  - `detect_conflicts(inputs: list[ConflictInput]) -> list[DetectedConflict]`
  - `VALUE_TOLERANCE = 0.10`, `FOUNDER_DIVERGENCE = 0.25`

**Rules (PRD §16.3) — exact thresholds:**

| Rule | Condition | Kind | Cross-exam |
|---|---|---|---|
| R1 | ≥1 `supports` + ≥1 `refutes`, **both tier ≤ 2**, overlapping scope | `chair_vs_chair` | yes if criticality ∈ {blocking, high} |
| R2 | Two items on same `variable`, overlapping scope, non-overlapping ranges **beyond ±10%** | `chair_vs_chair` | same condition |
| R3 | Founder assumption value V vs evidence value E, same variable, overlapping scope, `abs(V−E)/E > 0.25` | `founder_vs_world` | **always** |
| R4 | Critical assumption, **zero** evidence after investigation | `no_evidence` | no |
| R5 | Evidence exists but **none** overlaps `target_scope` | `scope_gap` | no |

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_conflict.py`:
```python
import pytest

from jury.engines.conflict import (
    AssumptionForConflict, ConflictInput, EvidenceForConflict, detect_conflicts,
)
from jury.schemas.enums import Chair, ConflictKind, ConflictRule, Criticality, Direction, Origin
from jury.schemas.scope import Scope

IN_SMB = Scope(geo="IN", segment="smb")
US_ENT = Scope(geo="US", segment="enterprise")


def e(eid="e1", chair="market", direction="supports", variable=None, value=None,
      tier=1, scope=IN_SMB, vmin=None, vmax=None) -> EvidenceForConflict:
    return EvidenceForConflict(id=eid, chair=Chair(chair), direction=Direction(direction),
                               variable=variable, value_num=value, value_min=vmin,
                               value_max=vmax, tier=tier, scope=scope)


def a(origin="founder", criticality="blocking", var=None, val=None) -> AssumptionForConflict:
    return AssumptionForConflict(id="a1", origin=Origin(origin),
                                 criticality=Criticality(criticality),
                                 asserted_variable=var, asserted_value=val)


def only(kinds, conflicts):
    return [c for c in conflicts if c.kind in kinds]


# ── R1: chair vs chair, direction ────────────────────────────────────────────
def test_r1_fires_on_opposing_tier1_evidence_in_overlapping_scope():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1),
                  e("e2", chair="customer", direction="refutes", tier=1)])])
    r1 = [c for c in got if c.rule is ConflictRule.R1]
    assert len(r1) == 1
    assert r1[0].kind is ConflictKind.CHAIR_VS_CHAIR
    assert r1[0].triggers_cross_exam is True


def test_r1_ignores_tier3_and_below():
    """PRD §16.3 R1 requires BOTH items at tier <= 2. Forum anecdote does not
    get to start a fight with a pricing page."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1),
                  e("e2", direction="refutes", tier=4)])])
    assert not [c for c in got if c.rule is ConflictRule.R1]


def test_r1_ignores_non_overlapping_scope():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1, scope=IN_SMB),
                  e("e2", direction="refutes", tier=1, scope=US_ENT)])])
    assert not [c for c in got if c.rule is ConflictRule.R1]


def test_r1_does_not_trigger_cross_exam_for_medium_criticality():
    got = detect_conflicts([ConflictInput(
        assumption=a(criticality="medium"), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1),
                  e("e2", direction="refutes", tier=2)])])
    r1 = [c for c in got if c.rule is ConflictRule.R1]
    assert len(r1) == 1 and r1[0].triggers_cross_exam is False


# ── R2: numeric divergence beyond the tolerance band ────────────────────────
def test_r2_fires_beyond_the_ten_percent_band():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", chair="customer", variable="price_monthly", value=200.0)])])
    r2 = [c for c in got if c.rule is ConflictRule.R2]
    assert len(r2) == 1 and r2[0].kind is ConflictKind.CHAIR_VS_CHAIR


def test_r2_tolerates_values_inside_the_band():
    """105 vs 100 is 5% - measurement noise, not a contradiction."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", variable="price_monthly", value=105.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_boundary_exactly_ten_percent_does_not_fire():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", variable="price_monthly", value=110.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_ignores_different_variables():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", variable="delivery_cost", value=900.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_ignores_non_overlapping_scope():
    """The exact false positive PRD §12.1 warns about: Rs 149 US-SMB vs Rs 500 IN-enterprise."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0, scope=US_ENT),
                  e("e2", variable="price_monthly", value=500.0, scope=IN_SMB)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_uses_ranges_when_present_and_overlapping_ranges_do_not_conflict():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", vmin=100.0, vmax=200.0),
                  e("e2", variable="price_monthly", vmin=180.0, vmax=300.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_fires_on_disjoint_ranges():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", vmin=100.0, vmax=150.0),
                  e("e2", variable="price_monthly", vmin=400.0, vmax=500.0)])])
    assert [c for c in got if c.rule is ConflictRule.R2]


# ── R3: founder vs world. "The rule that earns the product its existence." ──
def test_r3_fires_beyond_twenty_five_percent_divergence():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0)])])
    r3 = [c for c in got if c.rule is ConflictRule.R3]
    assert len(r3) == 1
    assert r3[0].kind is ConflictKind.FOUNDER_VS_WORLD
    assert r3[0].triggers_cross_exam is True         # R3 ALWAYS triggers


def test_r3_always_triggers_cross_exam_even_at_low_criticality():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", criticality="low", var="price_monthly", val=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0)])])
    r3 = [c for c in got if c.rule is ConflictRule.R3]
    assert r3 and r3[0].triggers_cross_exam is True


def test_r3_tolerates_divergence_inside_twenty_five_percent():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=120.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R3]


def test_r3_does_not_fire_for_discovered_assumptions():
    """P2: only FOUNDER assertions can lose to the world."""
    got = detect_conflicts([ConflictInput(
        assumption=AssumptionForConflict(id="a1", origin=Origin.DISCOVERED,
                                         criticality=Criticality.BLOCKING,
                                         asserted_variable="price_monthly",
                                         asserted_value=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R3]


def test_r3_divergence_is_relative_to_evidence_not_to_the_claim():
    """PRD §16.3: abs(V - E) / E. The world is the denominator."""
    # V=100, E=50 -> |50|/50 = 1.0 > 0.25, fires
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="x", val=100.0), target_scope=IN_SMB,
        evidence=[e("e1", variable="x", value=50.0)])])
    assert [c for c in got if c.rule is ConflictRule.R3]


def test_r3_handles_zero_evidence_value_without_dividing_by_zero():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="x", val=100.0), target_scope=IN_SMB,
        evidence=[e("e1", variable="x", value=0.0)])])
    assert isinstance(got, list)      # must not raise


# ── R4: silence is a finding ────────────────────────────────────────────────
def test_r4_fires_for_a_critical_assumption_with_no_evidence():
    got = detect_conflicts([ConflictInput(assumption=a(criticality="blocking"),
                                          target_scope=IN_SMB, evidence=[])])
    r4 = [c for c in got if c.rule is ConflictRule.R4]
    assert len(r4) == 1
    assert r4[0].kind is ConflictKind.NO_EVIDENCE
    assert r4[0].triggers_cross_exam is False     # nothing to debate


def test_r4_does_not_fire_for_low_criticality():
    got = detect_conflicts([ConflictInput(assumption=a(criticality="low"),
                                          target_scope=IN_SMB, evidence=[])])
    assert not [c for c in got if c.rule is ConflictRule.R4]


def test_r4_does_not_fire_when_any_evidence_exists():
    got = detect_conflicts([ConflictInput(assumption=a(), target_scope=IN_SMB,
                                          evidence=[e("e1")])])
    assert not [c for c in got if c.rule is ConflictRule.R4]


# ── R5: scope gap is a gap, not a contradiction ─────────────────────────────
def test_r5_fires_when_no_evidence_covers_the_target_scope():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", scope=US_ENT), e("e2", scope=US_ENT)])])
    r5 = [c for c in got if c.rule is ConflictRule.R5]
    assert len(r5) == 1
    assert r5[0].kind is ConflictKind.SCOPE_GAP
    assert r5[0].triggers_cross_exam is False     # reported as a gap (F9)


def test_r5_does_not_fire_when_global_evidence_covers_the_target():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", scope=Scope(geo="GLOBAL", segment="smb"))])])
    assert not [c for c in got if c.rule is ConflictRule.R5]


def test_r5_does_not_fire_when_there_is_no_evidence_at_all():
    """With zero evidence R4 is the correct finding, not R5."""
    got = detect_conflicts([ConflictInput(assumption=a(), target_scope=IN_SMB,
                                          evidence=[])])
    assert not [c for c in got if c.rule is ConflictRule.R5]
    assert [c for c in got if c.rule is ConflictRule.R4]


# ── engine-level properties ─────────────────────────────────────────────────
def test_detection_is_deterministic_across_repeated_calls():
    """F9: deterministic. Same input, same output, same order."""
    inp = [ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0, tier=1),
                  e("e2", chair="customer", variable="price_monthly",
                    value=600.0, direction="refutes", tier=2)])]
    first = detect_conflicts(inp)
    for _ in range(20):
        again = detect_conflicts(inp)
        assert [(c.rule, c.kind, c.left_ref, c.right_ref) for c in again] == \
               [(c.rule, c.kind, c.left_ref, c.right_ref) for c in first]


def test_no_conflicts_on_a_clean_record():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=150.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0, tier=1),
                  e("e2", chair="customer", variable="price_monthly", value=152.0, tier=1)])])
    assert got == []


def test_severity_is_derived_from_criticality():
    got = detect_conflicts([ConflictInput(assumption=a(criticality="blocking"),
                                          target_scope=IN_SMB, evidence=[])])
    assert got[0].severity == "critical"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_conflict.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

`apps/api/jury/engines/conflict.py`:
```python
"""Conflict detection. PRD §16.3. Deterministic — no LLM anywhere in this module.

R3 is the rule that earns the product its existence: the founder's pitch is a
set of claims in the same system as everything else, and it is expected to lose.
"""
from dataclasses import dataclass, field
from itertools import combinations

from jury.engines.scope import covers_target, scopes_overlap
from jury.schemas.enums import (
    Chair, ConflictKind, ConflictRule, Criticality, Direction, Origin,
)
from jury.schemas.scope import Scope

VALUE_TOLERANCE = 0.10        # R2 band
FOUNDER_DIVERGENCE = 0.25     # R3 threshold
_CROSS_EXAM_CRITICALITY = frozenset({Criticality.BLOCKING, Criticality.HIGH})
_R4_CRITICALITY = frozenset({Criticality.BLOCKING, Criticality.HIGH, Criticality.MEDIUM})
_SEVERITY = {Criticality.BLOCKING: "critical", Criticality.HIGH: "high",
             Criticality.MEDIUM: "medium", Criticality.LOW: "low"}


@dataclass(frozen=True, slots=True)
class EvidenceForConflict:
    id: str
    chair: Chair
    direction: Direction
    variable: str | None
    value_num: float | None
    value_min: float | None
    value_max: float | None
    tier: int
    scope: Scope


@dataclass(frozen=True, slots=True)
class AssumptionForConflict:
    id: str
    origin: Origin
    criticality: Criticality
    asserted_variable: str | None = None
    asserted_value: float | None = None


@dataclass(frozen=True, slots=True)
class ConflictInput:
    assumption: AssumptionForConflict
    target_scope: Scope
    evidence: list[EvidenceForConflict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DetectedConflict:
    assumption_id: str
    kind: ConflictKind
    rule: ConflictRule
    left_ref: dict
    right_ref: dict | None
    severity: str
    triggers_cross_exam: bool


def _interval(e: EvidenceForConflict) -> tuple[float, float] | None:
    """Collapse an item to a numeric interval, or None if it carries no number."""
    if e.value_min is not None and e.value_max is not None:
        return (e.value_min, e.value_max)
    if e.value_num is not None:
        return (e.value_num, e.value_num)
    return None


def _diverges(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True if the two intervals are disjoint beyond the +/-10% tolerance band."""
    lo_a, hi_a = a
    lo_b, hi_b = b
    if lo_a <= hi_b and lo_b <= hi_a:       # overlapping intervals never conflict
        return False
    gap_low, gap_high = (hi_a, lo_b) if hi_a < lo_b else (hi_b, lo_a)
    anchor = abs(gap_low) or abs(gap_high)
    if anchor == 0:
        return gap_high != gap_low
    return (gap_high - gap_low) / anchor > VALUE_TOLERANCE


def _r1(inp: ConflictInput) -> list[DetectedConflict]:
    """Opposing directions, both tier <= 2, overlapping scope."""
    out: list[DetectedConflict] = []
    supports = [e for e in inp.evidence
                if e.direction is Direction.SUPPORTS and e.tier <= 2]
    refutes = [e for e in inp.evidence
               if e.direction is Direction.REFUTES and e.tier <= 2]
    for s in supports:
        for r in refutes:
            if not scopes_overlap(s.scope, r.scope):
                continue
            out.append(DetectedConflict(
                assumption_id=inp.assumption.id,
                kind=ConflictKind.CHAIR_VS_CHAIR,
                rule=ConflictRule.R1,
                left_ref={"type": "evidence", "id": s.id},
                right_ref={"type": "evidence", "id": r.id},
                severity=_SEVERITY[inp.assumption.criticality],
                triggers_cross_exam=(
                    inp.assumption.criticality in _CROSS_EXAM_CRITICALITY),
            ))
    return out


def _r2(inp: ConflictInput) -> list[DetectedConflict]:
    """Same variable, overlapping scope, numerically divergent beyond the band."""
    out: list[DetectedConflict] = []
    numeric = [e for e in inp.evidence if e.variable and _interval(e) is not None]
    for a, b in combinations(numeric, 2):
        if a.variable != b.variable:
            continue
        if not scopes_overlap(a.scope, b.scope):
            continue
        if not _diverges(_interval(a), _interval(b)):
            continue
        out.append(DetectedConflict(
            assumption_id=inp.assumption.id,
            kind=ConflictKind.CHAIR_VS_CHAIR,
            rule=ConflictRule.R2,
            left_ref={"type": "evidence", "id": a.id},
            right_ref={"type": "evidence", "id": b.id},
            severity=_SEVERITY[inp.assumption.criticality],
            triggers_cross_exam=(
                inp.assumption.criticality in _CROSS_EXAM_CRITICALITY),
        ))
    return out


def _r3(inp: ConflictInput) -> list[DetectedConflict]:
    """Founder vs world. abs(V - E) / E > 0.25. Always triggers cross-examination."""
    asm = inp.assumption
    if asm.origin is not Origin.FOUNDER:
        return []
    if asm.asserted_variable is None or asm.asserted_value is None:
        return []

    out: list[DetectedConflict] = []
    for e in inp.evidence:
        if e.variable != asm.asserted_variable or e.value_num is None:
            continue
        if not scopes_overlap(e.scope, inp.target_scope):
            continue
        if e.value_num == 0:
            diverges = asm.asserted_value != 0
        else:
            diverges = (abs(asm.asserted_value - e.value_num) / abs(e.value_num)
                        > FOUNDER_DIVERGENCE)
        if not diverges:
            continue
        out.append(DetectedConflict(
            assumption_id=asm.id,
            kind=ConflictKind.FOUNDER_VS_WORLD,
            rule=ConflictRule.R3,
            left_ref={"type": "assumption", "id": asm.id},
            right_ref={"type": "evidence", "id": e.id},
            severity=_SEVERITY[asm.criticality],
            triggers_cross_exam=True,      # PRD §16.3: R3 ALWAYS
        ))
    return out


def _r4(inp: ConflictInput) -> list[DetectedConflict]:
    """Critical assumption with zero evidence. Silence is a finding."""
    if inp.evidence or inp.assumption.criticality not in _R4_CRITICALITY:
        return []
    return [DetectedConflict(
        assumption_id=inp.assumption.id,
        kind=ConflictKind.NO_EVIDENCE,
        rule=ConflictRule.R4,
        left_ref={"type": "assumption", "id": inp.assumption.id},
        right_ref=None,
        severity=_SEVERITY[inp.assumption.criticality],
        triggers_cross_exam=False,     # reported, and it feeds the gate
    )]


def _r5(inp: ConflictInput) -> list[DetectedConflict]:
    """Evidence exists but none of it covers the founder's target scope."""
    if not inp.evidence:
        return []
    if any(covers_target(e.scope, inp.target_scope) for e in inp.evidence):
        return []
    return [DetectedConflict(
        assumption_id=inp.assumption.id,
        kind=ConflictKind.SCOPE_GAP,
        rule=ConflictRule.R5,
        left_ref={"type": "assumption", "id": inp.assumption.id},
        right_ref={"type": "evidence", "id": inp.evidence[0].id},
        severity=_SEVERITY[inp.assumption.criticality],
        triggers_cross_exam=False,     # a gap, not a contradiction (F9)
    )]


def detect_conflicts(inputs: list[ConflictInput]) -> list[DetectedConflict]:
    """Run R1-R5 over every assumption. Order is stable: input order, then R1..R5."""
    out: list[DetectedConflict] = []
    for inp in inputs:
        out.extend(_r1(inp))
        out.extend(_r2(inp))
        out.extend(_r3(inp))
        out.extend(_r4(inp))
        out.extend(_r5(inp))
    return out
```

Note: R4 fires for `medium` as well as `blocking`/`high`. PRD §16.3 says "critical assumption"; PRD §9.3's `open_critical` term uses `{blocking, high}`. Using `{blocking, high, medium}` for R4 reporting while the *gate* uses `{blocking, high}` is deliberate — reporting a medium-criticality silence is informative, and it does not affect the verdict. Recorded in `CHANGELOG.md`.

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_conflict.py -v
```
Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/engines/conflict.py apps/api/tests/engines/test_conflict.py
git commit -m "feat(engines): deterministic conflict engine R1-R5"
```

---

### Task 1.6: Economics — templates and solver

**Files:**
- Create: `apps/api/jury/engines/economics/__init__.py`, `templates.py`, `solver.py`
- Test: `apps/api/tests/engines/test_economics.py`

**Interfaces:**
- Produces:
  - `TEMPLATES: dict[str, Template]` keyed `marketplace_v1`, `saas_v1`, `d2c_v1`, `services_v1`
  - `Template` dataclass: `key`, `params: dict[str, ParamSpec]`, `compute: Callable[[dict[str, float]], ModelOutputs]`, `primary_output: str`
  - `ParamSpec` dataclass: `unit: str`, `lo: float`, `hi: float`, `default: float`
  - `solve(template_key: str, parameters: dict[str, Parameter]) -> ModelRunResult`
  - `ModelRunResult` dataclass: `outputs: ModelOutputs`, `breakpoints: list[Breakpoint]`, `sensitivity: list[SensitivityEntry]`, `viable: bool`

**PRD §16.5 requirements:** contribution margin, LTV, LTV/CAC, payback, monthly break-even volume. Breakpoints via `scipy.optimize.brentq`. Sensitivity by ±20% one-at-a-time elasticity, ranked descending. Monte Carlo explicitly out of scope. **No LLM arithmetic (P8).**

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_economics.py`:
```python
import pytest

from jury.engines.economics.solver import solve
from jury.engines.economics.templates import TEMPLATES
from jury.schemas.economics import Parameter
from jury.schemas.enums import Provenance


def p(value, unit="INR", provenance="founder_asserted") -> Parameter:
    return Parameter(value=value, unit=unit, provenance=Provenance(provenance))


# A hand-computable marketplace: AOV 1000, take 10%, so revenue/txn = 100.
# Costs: delivery 30, payment fee 2% of AOV = 20, support 10  => total 60.
# Contribution margin = 100 - 60 = 40 per transaction.
MARKETPLACE = {
    "aov": p(1000.0),
    "take_rate": p(0.10, "fraction"),
    "delivery_cost": p(30.0),
    "payment_fee": p(0.02, "fraction"),
    "support_cost_per_txn": p(10.0),
    "cac_buyer": p(400.0),
    "cac_supplier": p(0.0),
    "txn_per_buyer_month": p(2.0, "count"),
    "buyer_churn_monthly": p(0.10, "fraction"),
    "fixed_monthly": p(20000.0),
}


def test_all_four_templates_exist():
    assert set(TEMPLATES) == {"marketplace_v1", "saas_v1", "d2c_v1", "services_v1"}


def test_contribution_margin_matches_hand_computation():
    """PRD §19.2: economics solver must agree EXACTLY with hand-computed fixtures."""
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.contribution_margin == pytest.approx(40.0)


def test_ltv_matches_hand_computation():
    # lifetime months = 1 / churn = 10 ; txn = 2/mo ; CM = 40
    # LTV = 40 * 2 * 10 = 800
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.ltv == pytest.approx(800.0)


def test_ltv_cac_matches_hand_computation():
    # LTV 800 / CAC 400 = 2.0
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.ltv_cac == pytest.approx(2.0)


def test_payback_months_matches_hand_computation():
    # monthly contribution per buyer = 40 * 2 = 80 ; CAC 400 -> 5 months
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.payback_months == pytest.approx(5.0)


def test_breakeven_volume_matches_hand_computation():
    # fixed 20000 / CM 40 = 500 transactions per month
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.breakeven_volume_monthly == pytest.approx(500.0)


def test_viable_when_margin_positive_and_ltv_cac_above_one():
    assert solve("marketplace_v1", MARKETPLACE).viable is True


def test_not_viable_when_contribution_margin_is_negative():
    params = MARKETPLACE | {"delivery_cost": p(500.0)}
    r = solve("marketplace_v1", params)
    assert r.outputs.contribution_margin < 0
    assert r.viable is False


def test_not_viable_when_ltv_cac_below_one():
    params = MARKETPLACE | {"cac_buyer": p(5000.0)}
    assert solve("marketplace_v1", params).viable is False


# ── breakpoints: PRD §16.5, brentq ──────────────────────────────────────────
def test_delivery_cost_breakpoint_is_exact():
    """CM = 0 when delivery_cost = 100 - 20 - 10 = 70."""
    r = solve("marketplace_v1", MARKETPLACE)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["delivery_cost"].threshold == pytest.approx(70.0, abs=1e-6)
    assert bp["delivery_cost"].direction == "above"


def test_breakpoint_carries_a_renderable_sentence():
    """PRD §16.5: output is a sentence like 'the business becomes loss-making
    above Rs 38 delivery cost.'"""
    r = solve("marketplace_v1", MARKETPLACE)
    bp = next(b for b in r.breakpoints if b.variable == "delivery_cost")
    assert "delivery_cost" in bp.sentence or "delivery cost" in bp.sentence.lower()
    assert "70" in bp.sentence


def test_take_rate_breakpoint_is_exact():
    """CM = 0 when aov*take = 60, i.e. take_rate = 0.06."""
    r = solve("marketplace_v1", MARKETPLACE)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["take_rate"].threshold == pytest.approx(0.06, abs=1e-6)
    assert bp["take_rate"].direction == "below"


def test_no_breakpoint_reported_when_none_exists_in_range():
    """A parameter that cannot flip the sign anywhere in its plausible range
    must not be given a fabricated threshold.

    fixed_monthly and the CAC parameters do not appear in the contribution
    margin at all, so no value of them crosses zero. They must be ABSENT from
    breakpoints, not present with an invented number.
    """
    r = solve("marketplace_v1", MARKETPLACE)
    reported = {b.variable for b in r.breakpoints}
    assert "fixed_monthly" not in reported
    assert "cac_supplier" not in reported
    assert "delivery_cost" in reported          # this one genuinely has a root


def test_breakpoints_are_never_nan_or_infinite():
    import math
    r = solve("marketplace_v1", MARKETPLACE)
    for b in r.breakpoints:
        assert math.isfinite(b.threshold)


# ── sensitivity: PRD §16.5, +/-20% one-at-a-time elasticity ────────────────
def test_sensitivity_is_ranked_descending_by_absolute_elasticity():
    r = solve("marketplace_v1", MARKETPLACE)
    mags = [abs(s.elasticity) for s in r.sensitivity]
    assert mags == sorted(mags, reverse=True)


def test_sensitivity_covers_every_template_parameter():
    r = solve("marketplace_v1", MARKETPLACE)
    assert {s.variable for s in r.sensitivity} == set(MARKETPLACE)


def test_sensitivity_carries_provenance_so_experiments_can_filter_on_it():
    """PRD §16.6: the join that makes four pillars one machine."""
    params = MARKETPLACE | {"aov": p(1000.0, "INR", "evidence_backed")}
    r = solve("marketplace_v1", params)
    aov = next(s for s in r.sensitivity if s.variable == "aov")
    assert aov.provenance is Provenance.EVIDENCE_BACKED
    take = next(s for s in r.sensitivity if s.variable == "take_rate")
    assert take.provenance is Provenance.FOUNDER_ASSERTED


def test_aov_and_take_rate_are_the_most_sensitive_in_this_fixture():
    """Both scale revenue linearly, so they must outrank support cost."""
    r = solve("marketplace_v1", MARKETPLACE)
    top = {s.variable for s in r.sensitivity[:2]}
    assert top == {"aov", "take_rate"}


def test_zero_valued_parameter_does_not_break_elasticity():
    params = MARKETPLACE | {"cac_supplier": p(0.0)}
    r = solve("marketplace_v1", params)
    entry = next(s for s in r.sensitivity if s.variable == "cac_supplier")
    assert entry.elasticity == 0.0


# ── determinism and reproducibility ────────────────────────────────────────
def test_solve_is_deterministic():
    """PRD §11.2 dec. 4: reproducible, diffable results across runs."""
    a = solve("marketplace_v1", MARKETPLACE)
    b = solve("marketplace_v1", MARKETPLACE)
    assert a.outputs.model_dump() == b.outputs.model_dump()
    assert [x.model_dump() for x in a.breakpoints] == [x.model_dump() for x in b.breakpoints]
    assert [x.model_dump() for x in a.sensitivity] == [x.model_dump() for x in b.sensitivity]


def test_missing_parameter_uses_the_template_default_and_marks_it_asserted():
    params = {k: v for k, v in MARKETPLACE.items() if k != "support_cost_per_txn"}
    r = solve("marketplace_v1", params)
    entry = next(s for s in r.sensitivity if s.variable == "support_cost_per_txn")
    assert entry.provenance is Provenance.FOUNDER_ASSERTED


def test_unknown_parameter_is_rejected_not_silently_ignored():
    with pytest.raises(ValueError, match="unknown parameter"):
        solve("marketplace_v1", MARKETPLACE | {"vibes": p(1.0)})


def test_unknown_template_is_rejected():
    with pytest.raises(KeyError):
        solve("nonexistent_v1", MARKETPLACE)


# ── saas template ──────────────────────────────────────────────────────────
SAAS = {
    "price_monthly": p(1000.0),
    "cogs_monthly": p(200.0),
    "cac": p(4000.0),
    "churn_monthly": p(0.05, "fraction"),
    "fixed_monthly": p(50000.0),
}


def test_saas_contribution_and_ltv_match_hand_computation():
    # CM = 1000 - 200 = 800 ; lifetime = 1/0.05 = 20 ; LTV = 16000 ; LTV/CAC = 4
    r = solve("saas_v1", SAAS)
    assert r.outputs.contribution_margin == pytest.approx(800.0)
    assert r.outputs.ltv == pytest.approx(16000.0)
    assert r.outputs.ltv_cac == pytest.approx(4.0)
    assert r.outputs.payback_months == pytest.approx(5.0)
    assert r.viable is True


def test_saas_churn_breakpoint_is_exact():
    """LTV/CAC = 1 when 800/churn = 4000, i.e. churn = 0.2."""
    r = solve("saas_v1", SAAS)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["churn_monthly"].threshold == pytest.approx(0.20, abs=1e-6)
    assert bp["churn_monthly"].direction == "above"


def test_no_llm_is_reachable_from_the_economics_engine():
    """P8: economics is computed, not described. Guard the import boundary."""
    import inspect

    from jury.engines.economics import solver, templates
    for mod in (solver, templates):
        src = inspect.getsource(mod)
        for banned in ("litellm", "openai", "groq", "completion(", "jury.llm"):
            assert banned not in src, f"{mod.__name__} references {banned}"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_economics.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write `jury/engines/economics/templates.py`**

```python
"""Typed economics templates. PRD §16.5 and §11.2 decision 4.

"Templates, not generated code." The LLM fills a validated parameter schema; it
never authors or executes code. This buys reproducible, diffable results across
runs, a provenance field per parameter so sensitivity can mechanically nominate
the next experiment, and elimination of the untrusted-code-execution surface.

P8: no LLM import may ever appear in this module. A test enforces that.
"""
from collections.abc import Callable
from dataclasses import dataclass

from jury.schemas.economics import ModelOutputs


@dataclass(frozen=True, slots=True)
class ParamSpec:
    unit: str
    lo: float           # lower bound of the plausible range, for brentq
    hi: float           # upper bound
    default: float


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    params: dict[str, ParamSpec]
    compute: Callable[[dict[str, float]], ModelOutputs]
    primary_output: str


def _finite_lifetime(churn: float) -> float:
    """Expected lifetime in months. Guard churn=0 so LTV stays finite."""
    return 1.0 / churn if churn > 1e-9 else 1e6


def _assemble(cm: float, txn_per_month: float, churn: float, cac: float,
              fixed_monthly: float) -> ModelOutputs:
    """Shared output assembly so every template reports the same five numbers."""
    lifetime = _finite_lifetime(churn)
    ltv = cm * txn_per_month * lifetime
    monthly_contribution = cm * txn_per_month
    return ModelOutputs(
        contribution_margin=cm,
        ltv=ltv,
        ltv_cac=(ltv / cac) if cac > 0 else float("inf"),
        payback_months=(cac / monthly_contribution) if monthly_contribution > 0 else None,
        breakeven_volume_monthly=(fixed_monthly / cm) if cm > 0 else None,
    )


# ── marketplace ─────────────────────────────────────────────────────────────
def _marketplace(v: dict[str, float]) -> ModelOutputs:
    revenue_per_txn = v["aov"] * v["take_rate"]
    cost_per_txn = (v["delivery_cost"]
                    + v["aov"] * v["payment_fee"]
                    + v["support_cost_per_txn"])
    cm = revenue_per_txn - cost_per_txn
    cac = v["cac_buyer"] + v["cac_supplier"]
    return _assemble(cm, v["txn_per_buyer_month"], v["buyer_churn_monthly"],
                     cac, v["fixed_monthly"])


# ── subscription saas ───────────────────────────────────────────────────────
def _saas(v: dict[str, float]) -> ModelOutputs:
    cm = v["price_monthly"] - v["cogs_monthly"]
    return _assemble(cm, 1.0, v["churn_monthly"], v["cac"], v["fixed_monthly"])


# ── d2c ─────────────────────────────────────────────────────────────────────
def _d2c(v: dict[str, float]) -> ModelOutputs:
    gross = v["price"] - v["cogs"] - v["fulfilment_cost"]
    cm = gross * (1.0 - v["return_rate"])
    return _assemble(cm, v["orders_per_customer_month"], v["churn_monthly"],
                     v["cac"], v["fixed_monthly"])


# ── services ────────────────────────────────────────────────────────────────
def _services(v: dict[str, float]) -> ModelOutputs:
    billable = v["hours_per_month"] * v["utilisation"]
    cm = billable * (v["rate_hourly"] - v["delivery_cost_hourly"])
    return _assemble(cm, 1.0, v["client_churn_monthly"], v["cac"], v["fixed_monthly"])


TEMPLATES: dict[str, Template] = {
    "marketplace_v1": Template(
        key="marketplace_v1",
        primary_output="contribution_margin",
        compute=_marketplace,
        params={
            "aov":                 ParamSpec("currency", 1.0, 1_000_000.0, 1000.0),
            "take_rate":           ParamSpec("fraction", 0.0001, 0.95, 0.10),
            "delivery_cost":       ParamSpec("currency_per_txn", 0.0, 1_000_000.0, 30.0),
            "payment_fee":         ParamSpec("fraction", 0.0, 0.30, 0.02),
            "support_cost_per_txn":ParamSpec("currency_per_txn", 0.0, 1_000_000.0, 10.0),
            "cac_buyer":           ParamSpec("currency", 0.0, 1_000_000.0, 400.0),
            "cac_supplier":        ParamSpec("currency", 0.0, 1_000_000.0, 0.0),
            "txn_per_buyer_month": ParamSpec("count", 0.01, 1000.0, 2.0),
            "buyer_churn_monthly": ParamSpec("fraction", 0.0001, 0.99, 0.10),
            "fixed_monthly":       ParamSpec("currency", 0.0, 100_000_000.0, 20000.0),
        },
    ),
    "saas_v1": Template(
        key="saas_v1",
        primary_output="contribution_margin",
        compute=_saas,
        params={
            "price_monthly": ParamSpec("currency_per_month", 1.0, 1_000_000.0, 1000.0),
            "cogs_monthly":  ParamSpec("currency_per_month", 0.0, 1_000_000.0, 200.0),
            "cac":           ParamSpec("currency", 0.0, 10_000_000.0, 4000.0),
            "churn_monthly": ParamSpec("fraction", 0.0001, 0.99, 0.05),
            "fixed_monthly": ParamSpec("currency", 0.0, 100_000_000.0, 50000.0),
        },
    ),
    "d2c_v1": Template(
        key="d2c_v1",
        primary_output="contribution_margin",
        compute=_d2c,
        params={
            "price":                     ParamSpec("currency", 1.0, 1_000_000.0, 1200.0),
            "cogs":                      ParamSpec("currency", 0.0, 1_000_000.0, 400.0),
            "fulfilment_cost":           ParamSpec("currency", 0.0, 1_000_000.0, 120.0),
            "return_rate":               ParamSpec("fraction", 0.0, 0.9, 0.08),
            "cac":                       ParamSpec("currency", 0.0, 1_000_000.0, 600.0),
            "orders_per_customer_month": ParamSpec("count", 0.01, 100.0, 0.5),
            "churn_monthly":             ParamSpec("fraction", 0.0001, 0.99, 0.20),
            "fixed_monthly":             ParamSpec("currency", 0.0, 100_000_000.0, 30000.0),
        },
    ),
    "services_v1": Template(
        key="services_v1",
        primary_output="contribution_margin",
        compute=_services,
        params={
            "rate_hourly":          ParamSpec("currency_per_hour", 1.0, 100_000.0, 2000.0),
            "delivery_cost_hourly": ParamSpec("currency_per_hour", 0.0, 100_000.0, 800.0),
            "hours_per_month":      ParamSpec("count", 1.0, 400.0, 160.0),
            "utilisation":          ParamSpec("fraction", 0.01, 1.0, 0.6),
            "client_churn_monthly": ParamSpec("fraction", 0.0001, 0.99, 0.08),
            "cac":                  ParamSpec("currency", 0.0, 10_000_000.0, 20000.0),
            "fixed_monthly":        ParamSpec("currency", 0.0, 100_000_000.0, 100000.0),
        },
    ),
}
```

Note: `ad_consumer` and `hardware` archetypes have no template. PRD §16.5 and §20 specify "templates for four archetypes". Runs on those two archetypes map to the nearest template (`ad_consumer → saas_v1`, `hardware → d2c_v1`) with the substitution recorded in `model_runs.template_key`. Deviation logged in `CHANGELOG.md`.

- [ ] **Step 4: Write `jury/engines/economics/solver.py`**

```python
"""Breakpoint and sensitivity solver. PRD §16.5.

Breakpoints are solved numerically with scipy.optimize.brentq over each
parameter's plausible range, holding the others fixed. Sensitivity is
one-at-a-time elasticity at +/-20%, ranked descending.

Monte Carlo is explicitly out of scope (PRD §16.5): a deterministic breakpoint
solve plus elasticity ranking delivers the same decision value at a fraction of
the build cost.

P8: no LLM import may ever appear in this module. A test enforces that.
"""
import math
from dataclasses import dataclass

from scipy.optimize import brentq

from jury.engines.economics.templates import TEMPLATES, Template
from jury.schemas.economics import (
    Breakpoint, ModelOutputs, Parameter, SensitivityEntry,
)
from jury.schemas.enums import Provenance

PERTURBATION = 0.20        # +/-20% one-at-a-time (PRD §16.5)
_VIABLE_LTV_CAC = 1.0


@dataclass(frozen=True, slots=True)
class ModelRunResult:
    template_key: str
    outputs: ModelOutputs
    breakpoints: list[Breakpoint]
    sensitivity: list[SensitivityEntry]
    viable: bool


def _resolve(template: Template,
             parameters: dict[str, Parameter]) -> tuple[dict[str, float],
                                                        dict[str, Provenance]]:
    """Fill missing parameters from template defaults, marked founder_asserted.

    A default is a guess, so it is founder_asserted by definition — which makes
    it eligible to become an experiment (PRD §16.6).
    """
    unknown = set(parameters) - set(template.params)
    if unknown:
        raise ValueError(f"unknown parameter(s) for {template.key}: {sorted(unknown)}")

    values: dict[str, float] = {}
    provenance: dict[str, Provenance] = {}
    for name, spec in template.params.items():
        given = parameters.get(name)
        if given is None:
            values[name] = spec.default
            provenance[name] = Provenance.FOUNDER_ASSERTED
        else:
            values[name] = float(given.value)
            provenance[name] = given.provenance
    return values, provenance


def _margin_at(template: Template, values: dict[str, float],
               name: str, x: float) -> float:
    probe = dict(values)
    probe[name] = x
    return template.compute(probe).contribution_margin


def _ltv_cac_at(template: Template, values: dict[str, float],
                name: str, x: float) -> float:
    probe = dict(values)
    probe[name] = x
    out = template.compute(probe)
    return out.ltv_cac - _VIABLE_LTV_CAC


def _solve_breakpoint(template: Template, values: dict[str, float], name: str,
                      objective, output_label: str) -> Breakpoint | None:
    """Find where `objective` crosses zero over the parameter's plausible range.

    brentq requires a sign change across the bracket. If there is none, no
    breakpoint exists in the plausible range and we report nothing rather than
    fabricating a threshold.
    """
    spec = template.params[name]
    try:
        f_lo = objective(template, values, name, spec.lo)
        f_hi = objective(template, values, name, spec.hi)
    except (ZeroDivisionError, OverflowError, ValueError):
        return None
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None

    try:
        root = brentq(lambda x: objective(template, values, name, x),
                      spec.lo, spec.hi, xtol=1e-9, maxiter=200)
    except (ValueError, RuntimeError):
        return None
    if not math.isfinite(root):
        return None

    # Direction: does exceeding the root break the business, or falling below it?
    above_is_worse = objective(template, values, name, min(root * 1.01 + 1e-9, spec.hi)) < 0
    direction = "above" if above_is_worse else "below"
    pretty = f"{root:,.2f}".rstrip("0").rstrip(".")
    label = name.replace("_", " ")
    sentence = (f"The business becomes unviable {direction} "
                f"{pretty} {spec.unit} of {label}.")
    return Breakpoint(variable=name, threshold=float(root), direction=direction,
                      unit=spec.unit, output=output_label, sentence=sentence)


def _elasticity(template: Template, values: dict[str, float], name: str) -> float:
    """Proportional change in the primary output for a +/-20% parameter change.

    Averaging the up and down perturbation makes the measure symmetric, which
    matters because a tornado chart is read as a magnitude ranking.
    """
    base = template.compute(values).contribution_margin
    x = values[name]
    if x == 0 or base == 0:
        return 0.0

    deltas = []
    for factor in (1.0 + PERTURBATION, 1.0 - PERTURBATION):
        spec = template.params[name]
        probe = dict(values)
        probe[name] = min(max(x * factor, spec.lo), spec.hi)
        try:
            perturbed = template.compute(probe).contribution_margin
        except (ZeroDivisionError, OverflowError):
            continue
        if math.isfinite(perturbed):
            deltas.append(abs((perturbed - base) / base) / PERTURBATION)
    return sum(deltas) / len(deltas) if deltas else 0.0


def solve(template_key: str, parameters: dict[str, Parameter]) -> ModelRunResult:
    """Execute the model, solve breakpoints, rank sensitivity.

    Deterministic and reproducible: the same parameters always yield the same
    outputs, breakpoints and ranking, which is what makes model runs diffable
    across ledger versions (PRD §11.2 decision 4).
    """
    template = TEMPLATES[template_key]
    values, provenance = _resolve(template, parameters)
    outputs = template.compute(values)

    breakpoints: list[Breakpoint] = []
    for name in template.params:
        bp = _solve_breakpoint(template, values, name, _margin_at,
                               "contribution_margin")
        if bp is None:
            bp = _solve_breakpoint(template, values, name, _ltv_cac_at, "ltv_cac")
        if bp is not None:
            breakpoints.append(bp)
    breakpoints.sort(key=lambda b: b.variable)

    sensitivity = [
        SensitivityEntry(variable=name,
                         elasticity=_elasticity(template, values, name),
                         provenance=provenance[name])
        for name in template.params
    ]
    # Descending by magnitude, then by name so ties are stable and diffable.
    sensitivity.sort(key=lambda s: (-abs(s.elasticity), s.variable))

    viable = (outputs.contribution_margin > 0
              and outputs.ltv_cac >= _VIABLE_LTV_CAC)

    return ModelRunResult(template_key=template_key, outputs=outputs,
                          breakpoints=breakpoints, sensitivity=sensitivity,
                          viable=viable)
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_economics.py -v
```
Expected: 26 passed. If a hand-computed assertion disagrees, **the test is right and the implementation is wrong** — PRD §19.2 demands exact agreement.

- [ ] **Step 6: Commit**

```bash
git add apps/api/jury/engines/economics apps/api/tests/engines/test_economics.py
git commit -m "feat(engines): typed economics templates with brentq breakpoints and elasticity"
```

---

### Task 1.7: Experiment generator and criterion evaluator

**Files:**
- Create: `apps/api/jury/engines/experiments.py`, `apps/api/jury/engines/criterion.py`
- Test: `apps/api/tests/engines/test_experiments.py`, `apps/api/tests/engines/test_criterion.py`

**Interfaces:**
- Produces:
  - `generate_experiments(sensitivity: list[SensitivityEntry], assumption_for_variable: dict[str, str], top_k: int = 5) -> list[ExperimentDraft]`
  - `VARIABLE_METHODS: dict[str, MethodSpec]`
  - `evaluate_criterion(spec: CriterionSpec, result_value: float) -> bool`
  - `status_for_result(spec, result_value) -> ExperimentStatus`

**The join (PRD §16.6) — this is what makes four pillars one machine:**
```
sensitivity ranking
  → filter provenance = 'founder_asserted'
      → the highest-sensitivity parameter that is still a guess
          → is, by construction, the highest-value thing to go learn
              → becomes experiment #1
```

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/engines/test_experiments.py`:
```python
import pytest

from jury.engines.experiments import generate_experiments
from jury.schemas.economics import SensitivityEntry
from jury.schemas.enums import ExperimentMethod, Provenance


def s(variable, elasticity, provenance="founder_asserted") -> SensitivityEntry:
    return SensitivityEntry(variable=variable, elasticity=elasticity,
                            provenance=Provenance(provenance))


MAP = {"price_monthly": "a-price", "delivery_cost": "a-delivery",
       "take_rate": "a-take", "cac": "a-cac", "churn_monthly": "a-churn",
       "aov": "a-aov"}


def test_evidence_backed_parameters_are_excluded():
    """PRD §16.6: filter provenance = 'founder_asserted'. There is nothing to
    learn about a parameter that already has evidence."""
    out = generate_experiments([s("aov", 9.0, "evidence_backed"),
                                s("price_monthly", 1.0)], MAP)
    assert [e.target_variable for e in out] == ["price_monthly"]


def test_highest_sensitivity_guess_becomes_experiment_one():
    out = generate_experiments([s("delivery_cost", 0.4), s("price_monthly", 3.0)], MAP)
    assert out[0].target_variable == "price_monthly"
    assert out[0].priority == 1


def test_priority_is_dense_and_starts_at_one():
    out = generate_experiments([s("price_monthly", 3.0), s("delivery_cost", 2.0),
                                s("cac", 1.0)], MAP)
    assert [e.priority for e in out] == [1, 2, 3]


def test_top_k_is_respected():
    entries = [s(v, float(9 - i)) for i, v in enumerate(MAP)]
    assert len(generate_experiments(entries, MAP, top_k=3)) == 3


def test_every_experiment_has_a_non_null_kill_criterion():
    """P9: required before the plan can be exported."""
    out = generate_experiments([s("price_monthly", 2.0), s("delivery_cost", 1.0)], MAP)
    assert out and all(e.kill_criterion and e.criterion_spec for e in out)


def test_criterion_spec_is_machine_evaluable():
    out = generate_experiments([s("price_monthly", 2.0)], MAP)
    spec = out[0].criterion_spec
    assert spec.metric and spec.comparator and spec.threshold is not None


def test_price_maps_to_presale_or_fake_door():
    """PRD §16.6 variable-to-method table."""
    out = generate_experiments([s("price_monthly", 2.0)], MAP)
    assert out[0].method in (ExperimentMethod.PRESALE, ExperimentMethod.FAKE_DOOR)


def test_delivery_cost_maps_to_supplier_quote_and_is_free():
    out = generate_experiments([s("delivery_cost", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.SUPPLIER_QUOTE
    assert out[0].est_cost == 0


def test_take_rate_maps_to_interview_script():
    out = generate_experiments([s("take_rate", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.INTERVIEW_SCRIPT


def test_cac_maps_to_landing_ctr():
    out = generate_experiments([s("cac", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.LANDING_CTR


def test_retention_maps_to_a_documented_proxy_with_a_stated_limitation():
    """Spec §26.6: no 30-day experiment measures retention honestly, and the
    product must state that rather than paper over it."""
    out = generate_experiments([s("churn_monthly", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.DOCUMENTED_PROXY
    assert out[0].limitation and "retention" in out[0].limitation.lower()


def test_every_experiment_has_cost_and_duration():
    out = generate_experiments([s(v, 1.0) for v in MAP], MAP)
    assert all(e.est_days is not None and e.est_cost is not None for e in out)


def test_variables_without_a_mapped_assumption_are_skipped():
    out = generate_experiments([s("orphan_variable", 5.0), s("price_monthly", 1.0)], MAP)
    assert [e.target_variable for e in out] == ["price_monthly"]


def test_unmapped_variable_class_is_skipped_rather_than_guessed():
    out = generate_experiments([s("mystery", 5.0)], {"mystery": "a-x"})
    assert out == []


def test_generation_is_deterministic():
    entries = [s("price_monthly", 2.0), s("delivery_cost", 2.0)]
    a = generate_experiments(entries, MAP)
    b = generate_experiments(entries, MAP)
    assert [x.model_dump() for x in a] == [x.model_dump() for x in b]


def test_instructions_are_substantive_not_a_placeholder():
    out = generate_experiments([s("price_monthly", 2.0)], MAP)
    assert len(out[0].instructions) >= 40
    assert "TODO" not in out[0].instructions
```

`apps/api/tests/engines/test_criterion.py`:
```python
import pytest

from jury.engines.criterion import evaluate_criterion, status_for_result
from jury.schemas.experiment import CriterionSpec


def spec(comparator=">=", threshold=4.0, metric="prepay_count", n=20) -> CriterionSpec:
    return CriterionSpec(metric=metric, comparator=comparator,
                         threshold=threshold, n=n)


@pytest.mark.parametrize("comparator,threshold,value,expected", [
    (">=", 4.0, 4.0, True),    (">=", 4.0, 3.9, False),   (">=", 4.0, 5.0, True),
    (">",  4.0, 4.0, False),   (">",  4.0, 4.1, True),
    ("<=", 4.0, 4.0, True),    ("<=", 4.0, 4.1, False),
    ("<",  4.0, 4.0, False),   ("<",  4.0, 3.9, True),
    ("==", 4.0, 4.0, True),    ("==", 4.0, 4.0001, False),
])
def test_every_comparator_evaluates_exactly(comparator, threshold, value, expected):
    """PRD §19.2: kill-criterion evaluation must be 100%."""
    assert evaluate_criterion(spec(comparator, threshold), value) is expected


def test_the_prd_worked_example():
    """PRD §7.10: 3/20 pre-paid against a criterion of >=4/20 -> refuted."""
    s = CriterionSpec(metric="prepay_count", comparator=">=", threshold=4, n=20)
    assert evaluate_criterion(s, 3.0) is False
    assert status_for_result(s, 3.0) == "failed"
    assert status_for_result(s, 4.0) == "passed"


def test_evaluation_is_mechanical_and_repeatable():
    """PRD §16.6: pre-registering the threshold makes the ledger update mechanical
    rather than another model judgement."""
    s = spec()
    for _ in range(50):
        assert evaluate_criterion(s, 3.9999) is False
```

- [ ] **Step 2: Run to verify both fail**

```bash
cd apps/api && uv run pytest tests/engines/test_experiments.py tests/engines/test_criterion.py -v
```
Expected: FAIL — modules missing.

- [ ] **Step 3: Write `jury/engines/criterion.py`**

```python
"""Kill-criterion evaluation. P9.

Pre-registering the threshold is what stops the founder returning with an
ambiguous result and rationalising it, and it makes the ledger update mechanical
rather than another model judgement (PRD §16.6).
"""
import operator

from jury.schemas.enums import Comparator
from jury.schemas.experiment import CriterionSpec

_OPS = {
    Comparator.GTE: operator.ge,
    Comparator.GT: operator.gt,
    Comparator.LTE: operator.le,
    Comparator.LT: operator.lt,
    Comparator.EQ: operator.eq,
}


def evaluate_criterion(spec: CriterionSpec, result_value: float) -> bool:
    """True if the observed value passes the pre-registered criterion."""
    return bool(_OPS[spec.comparator](result_value, spec.threshold))


def status_for_result(spec: CriterionSpec, result_value: float) -> str:
    """Map a logged result onto experiments.status. No judgement involved."""
    return "passed" if evaluate_criterion(spec, result_value) else "failed"
```

- [ ] **Step 4: Write `jury/engines/experiments.py`**

```python
"""Experiment generation. PRD §16.6.

The join that makes the four pillars one machine instead of four features:

    sensitivity ranking
      -> filter provenance = 'founder_asserted'
          -> the highest-sensitivity parameter that is still a guess
              -> is, by construction, the highest-value thing to go learn
                  -> becomes experiment #1
"""
from dataclasses import dataclass

from jury.schemas.economics import SensitivityEntry
from jury.schemas.enums import Comparator, ExperimentMethod, Provenance
from jury.schemas.experiment import CriterionSpec, ExperimentDraft


@dataclass(frozen=True, slots=True)
class MethodSpec:
    method: ExperimentMethod
    instructions: str
    kill_criterion: str
    criterion: CriterionSpec
    est_cost: float
    est_days: int
    limitation: str | None = None


# PRD §16.6 variable-to-method mapping. Keyed by exact variable name; prefix
# fallbacks below catch families like wtp_*.
VARIABLE_METHODS: dict[str, MethodSpec] = {
    "price_monthly": MethodSpec(
        method=ExperimentMethod.PRESALE,
        instructions=(
            "Build a one-page offer at the asserted price with a real checkout. "
            "Drive 20 qualified visitors from the channel you actually intend to "
            "use. Count how many complete a pre-payment, not how many say they "
            "would. Refund everyone afterwards."),
        kill_criterion="Fewer than 4 of 20 qualified visitors pre-pay at the asserted price.",
        criterion=CriterionSpec(metric="prepay_count", comparator=Comparator.GTE,
                                threshold=4, n=20),
        est_cost=5000.0, est_days=7),
    "take_rate": MethodSpec(
        method=ExperimentMethod.INTERVIEW_SCRIPT,
        instructions=(
            "Speak to 10 supply-side participants. State the commission as a fact, "
            "not a question, and ask them to commit to a first listing. Record "
            "acceptance before any negotiation, and count only unprompted yeses."),
        kill_criterion="Fewer than 5 of 10 supply-side contacts accept the stated commission.",
        criterion=CriterionSpec(metric="accept_count", comparator=Comparator.GTE,
                                threshold=5, n=10),
        est_cost=0.0, est_days=7),
    "delivery_cost": MethodSpec(
        method=ExperimentMethod.SUPPLIER_QUOTE,
        instructions=(
            "Request written quotes from at least 5 providers for your actual "
            "volume, weight and route. Use the median of the written quotes, not "
            "the cheapest, and keep the emails as your source."),
        kill_criterion="Median written quote exceeds the break-even delivery cost from the model.",
        criterion=CriterionSpec(metric="median_quote", comparator=Comparator.LTE,
                                threshold=0.0, n=5),
        est_cost=0.0, est_days=5),
    "cac": MethodSpec(
        method=ExperimentMethod.LANDING_CTR,
        instructions=(
            "Run a landing page against the intended paid channel with a fixed "
            "budget. Measure cost per completed signup, not cost per click, and "
            "run long enough to clear the platform's learning phase."),
        kill_criterion="Measured cost per signup exceeds the modelled CAC.",
        criterion=CriterionSpec(metric="cost_per_signup", comparator=Comparator.LTE,
                                threshold=0.0, n=None),
        est_cost=10000.0, est_days=14),
    "aov": MethodSpec(
        method=ExperimentMethod.FAKE_DOOR,
        instructions=(
            "Publish the real basket at the assumed average order value with a "
            "working cart. Measure completed checkout attempts and the actual "
            "basket value distribution across at least 30 sessions."),
        kill_criterion="Median attempted basket value falls below the asserted AOV.",
        criterion=CriterionSpec(metric="median_basket", comparator=Comparator.GTE,
                                threshold=0.0, n=30),
        est_cost=5000.0, est_days=10),
    "churn_monthly": MethodSpec(
        method=ExperimentMethod.DOCUMENTED_PROXY,
        instructions=(
            "Retention cannot be measured honestly inside 30 days. Substitute a "
            "documented proxy: published churn or review-attrition figures for the "
            "two closest comparable products, cited by URL. Record the proxy and "
            "the gap between proxy and your own case."),
        kill_criterion=(
            "Comparable published churn exceeds the modelled monthly churn, and no "
            "structural reason for a difference is documented."),
        criterion=CriterionSpec(metric="comparable_churn_monthly",
                                comparator=Comparator.LTE, threshold=0.0, n=2),
        est_cost=0.0, est_days=3,
        limitation=(
            "No 30-day experiment can measure retention honestly. This is a "
            "documented proxy, not a measurement, and the verdict treats it as such.")),
    "regulatory_permitted": MethodSpec(
        method=ExperimentMethod.REGISTRY_CHECK,
        instructions=(
            "Identify the governing regulator and search its public register for "
            "the licence or registration your model requires. If the register is "
            "ambiguous, send a written enquiry and keep the reference number."),
        kill_criterion="The activity requires a licence you cannot obtain within 90 days.",
        criterion=CriterionSpec(metric="licence_obtainable_days",
                                comparator=Comparator.LTE, threshold=90, n=None),
        est_cost=0.0, est_days=21),
}

# Variable families that share a method with a canonical variable above.
_PREFIX_ALIASES: tuple[tuple[str, str], ...] = (
    ("wtp_", "price_monthly"),
    ("price", "price_monthly"),
    ("cac_", "cac"),
    ("churn", "churn_monthly"),
    ("retention", "churn_monthly"),
    ("cost_per", "delivery_cost"),
    ("fulfilment", "delivery_cost"),
    ("cogs", "delivery_cost"),
)


def _method_for(variable: str) -> MethodSpec | None:
    if variable in VARIABLE_METHODS:
        return VARIABLE_METHODS[variable]
    v = variable.lower()
    for prefix, canonical in _PREFIX_ALIASES:
        if v.startswith(prefix):
            return VARIABLE_METHODS[canonical]
    return None       # unmapped: skip rather than invent a method


def generate_experiments(
    sensitivity: list[SensitivityEntry],
    assumption_for_variable: dict[str, str],
    top_k: int = 5,
) -> list[ExperimentDraft]:
    """Top-k founder-asserted, highest-sensitivity parameters, as experiments (F13).

    Every returned draft carries a non-null kill criterion and a machine-evaluable
    criterion_spec (P9).
    """
    guesses = [s for s in sensitivity if s.provenance is Provenance.FOUNDER_ASSERTED]
    guesses.sort(key=lambda s: (-abs(s.elasticity), s.variable))

    drafts: list[ExperimentDraft] = []
    for entry in guesses:
        if len(drafts) >= top_k:
            break
        assumption_id = assumption_for_variable.get(entry.variable)
        if assumption_id is None:
            continue
        spec = _method_for(entry.variable)
        if spec is None:
            continue
        drafts.append(ExperimentDraft(
            assumption_id=assumption_id,
            target_variable=entry.variable,
            method=spec.method,
            instructions=spec.instructions,
            kill_criterion=spec.kill_criterion,
            criterion_spec=spec.criterion,
            est_cost=spec.est_cost,
            est_days=spec.est_days,
            priority=len(drafts) + 1,
            limitation=spec.limitation,
        ))
    return drafts
```

- [ ] **Step 5: Run to verify both pass**

```bash
cd apps/api && uv run pytest tests/engines/test_experiments.py tests/engines/test_criterion.py -v
```
Expected: 16 + 14 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/api/jury/engines/experiments.py apps/api/jury/engines/criterion.py apps/api/tests/engines/test_experiments.py apps/api/tests/engines/test_criterion.py
git commit -m "feat(engines): experiment generator and mechanical kill-criterion evaluation"
```

---

### Task 1.8: Ledger diff engine

**Files:**
- Create: `apps/api/jury/engines/diff.py`
- Test: `apps/api/tests/engines/test_diff.py`

**Interfaces:**
- Produces:
  - `Snapshot` TypedDict: `assumptions`, `evidence_counts`, `conflicts`, `parameters`, `breakpoints`, `confidence`, `verdict`
  - `compute_diff(previous: Snapshot | None, current: Snapshot) -> list[DiffEntry]`
  - `DiffEntry` dataclass: `type: str`, `subject: str`, `before`, `after`, `detail: dict`
  - `causal_sentence(entries: list[DiffEntry]) -> str`

**Diff types (PRD §16.8):** `assumption_status_change`, `evidence_added`, `assumption_discovered`, `conflict_resolved`, `parameter_provenance_change`, `breakpoint_moved`, `confidence_change`, `verdict_change`.

**The target render (PRD §7.10):**
> `pricing_wtp` moved **uncertain → refuted** because 3/20 pre-paid against a criterion of ≥4/20. This moved `price_monthly` from `founder_asserted ₹499` to `evidence_backed ₹249`, which moved the break-even delivery cost from ₹38 to ₹19. Verdict changed **PROCEED → PIVOT**.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/engines/test_diff.py`:
```python
import pytest

from jury.engines.diff import causal_sentence, compute_diff

V1 = {
    "assumptions": {"a-price": {"statement": "pricing_wtp", "status": "uncertain"}},
    "evidence_counts": {"market": {"1": 2}},
    "conflicts": {},
    "parameters": {"price_monthly": {"value": 499.0, "provenance": "founder_asserted"}},
    "breakpoints": {"delivery_cost": 38.0},
    "confidence": {"total": 52.0, "coverage": 0.8, "mean_strength": 0.5,
                   "contradiction": 0.0, "open_critical": 0.2},
    "verdict": "PROCEED",
}

V2 = {
    "assumptions": {"a-price": {"statement": "pricing_wtp", "status": "refuted"}},
    "evidence_counts": {"market": {"1": 2}, "customer": {"4": 3}},
    "conflicts": {},
    "parameters": {"price_monthly": {"value": 249.0, "provenance": "evidence_backed"}},
    "breakpoints": {"delivery_cost": 19.0},
    "confidence": {"total": 61.0, "coverage": 0.9, "mean_strength": 0.5,
                   "contradiction": 0.0, "open_critical": 0.1},
    "verdict": "PIVOT",
}


def types_of(entries):
    return [e.type for e in entries]


def test_first_version_has_no_diff_but_does_not_crash():
    entries = compute_diff(None, V1)
    assert entries == []


def test_status_change_is_detected():
    entries = compute_diff(V1, V2)
    e = next(x for x in entries if x.type == "assumption_status_change")
    assert (e.before, e.after) == ("uncertain", "refuted")
    assert e.subject == "a-price"


def test_parameter_provenance_change_is_detected():
    e = next(x for x in compute_diff(V1, V2)
             if x.type == "parameter_provenance_change")
    assert e.before == "founder_asserted" and e.after == "evidence_backed"
    assert e.detail["value_before"] == 499.0 and e.detail["value_after"] == 249.0


def test_breakpoint_move_is_detected():
    e = next(x for x in compute_diff(V1, V2) if x.type == "breakpoint_moved")
    assert (e.before, e.after) == (38.0, 19.0)


def test_verdict_change_is_detected():
    e = next(x for x in compute_diff(V1, V2) if x.type == "verdict_change")
    assert (e.before, e.after) == ("PROCEED", "PIVOT")


def test_confidence_change_names_which_component_moved():
    """PRD §16.8: 'old -> new, with which of the four components moved'."""
    e = next(x for x in compute_diff(V1, V2) if x.type == "confidence_change")
    assert e.before == 52.0 and e.after == 61.0
    assert set(e.detail["components_moved"]) == {"coverage", "open_critical"}


def test_evidence_added_is_counted_by_chair_and_tier():
    e = next(x for x in compute_diff(V1, V2) if x.type == "evidence_added")
    assert e.detail["by_chair"]["customer"] == 3
    assert e.detail["by_tier"]["4"] == 3


def test_newly_discovered_assumption_is_reported():
    v3 = {**V2, "assumptions": {**V2["assumptions"],
                                "a-new": {"statement": "supply liquidity",
                                          "status": "no_evidence",
                                          "origin": "discovered",
                                          "discovered_by": "precedent"}}}
    e = next(x for x in compute_diff(V2, v3) if x.type == "assumption_discovered")
    assert e.subject == "a-new"
    assert e.detail["discovered_by"] == "precedent"


def test_conflict_resolution_is_reported():
    v1 = {**V1, "conflicts": {"c1": {"status": "open", "kind": "founder_vs_world",
                                     "conceding_chair": None}}}
    v2 = {**V2, "conflicts": {"c1": {"status": "conceded", "kind": "founder_vs_world",
                                     "conceding_chair": "market"}}}
    e = next(x for x in compute_diff(v1, v2) if x.type == "conflict_resolved")
    assert e.after == "conceded"
    assert e.detail["conceding_chair"] == "market"


def test_identical_snapshots_produce_no_entries():
    assert compute_diff(V1, V1) == []


def test_diff_is_deterministic_and_ordered():
    a, b = compute_diff(V1, V2), compute_diff(V1, V2)
    assert types_of(a) == types_of(b)


def test_causal_sentence_renders_a_single_chain_not_a_list():
    """PRD §16.8: 'renders the causal chain as a single sentence path, not a
    list of unrelated changes.'"""
    sentence = causal_sentence(compute_diff(V1, V2))
    assert sentence.count("\n") == 0
    for fragment in ("pricing_wtp", "uncertain", "refuted", "499", "249",
                     "38", "19", "PROCEED", "PIVOT"):
        assert fragment in sentence, fragment


def test_causal_sentence_is_empty_when_nothing_changed():
    assert causal_sentence([]) == ""


def test_causal_sentence_survives_a_partial_chain():
    """Only a verdict change, no parameter or breakpoint movement."""
    v2 = {**V1, "verdict": "STOP"}
    sentence = causal_sentence(compute_diff(V1, v2))
    assert "PROCEED" in sentence and "STOP" in sentence
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/engines/test_diff.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

`apps/api/jury/engines/diff.py`:
```python
"""Ledger diff. PRD §16.8.

On each new version, compute a typed diff against the previous snapshot. The
return-visit screen renders the causal chain as a single sentence path, not a
list of unrelated changes — PRD calls this "the cheapest-to-build and strongest
demo beat in the product."

A regenerated report is explicitly a failure mode (PRD §2.2); the ledger diffs.
"""
from dataclasses import dataclass, field
from typing import Any

DIFF_ORDER = (
    "assumption_status_change",
    "assumption_discovered",
    "evidence_added",
    "conflict_resolved",
    "parameter_provenance_change",
    "breakpoint_moved",
    "confidence_change",
    "verdict_change",
)
_COMPONENTS = ("coverage", "mean_strength", "contradiction", "open_critical")


@dataclass(frozen=True, slots=True)
class DiffEntry:
    type: str
    subject: str
    before: Any
    after: Any
    detail: dict = field(default_factory=dict)


def _assumption_entries(prev: dict, curr: dict) -> list[DiffEntry]:
    out: list[DiffEntry] = []
    for aid, now in sorted(curr.items()):
        was = prev.get(aid)
        if was is None:
            out.append(DiffEntry(
                type="assumption_discovered", subject=aid,
                before=None, after=now.get("status"),
                detail={"statement": now.get("statement"),
                        "discovered_by": now.get("discovered_by")}))
        elif was.get("status") != now.get("status"):
            out.append(DiffEntry(
                type="assumption_status_change", subject=aid,
                before=was.get("status"), after=now.get("status"),
                detail={"statement": now.get("statement")}))
    return out


def _evidence_entry(prev: dict, curr: dict) -> list[DiffEntry]:
    by_chair: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    total = 0
    for chair, tiers in sorted(curr.items()):
        for tier, count in sorted(tiers.items()):
            added = count - prev.get(chair, {}).get(tier, 0)
            if added <= 0:
                continue
            by_chair[chair] = by_chair.get(chair, 0) + added
            by_tier[str(tier)] = by_tier.get(str(tier), 0) + added
            total += added
    if total == 0:
        return []
    return [DiffEntry(type="evidence_added", subject="ledger",
                      before=None, after=total,
                      detail={"by_chair": by_chair, "by_tier": by_tier})]


def _conflict_entries(prev: dict, curr: dict) -> list[DiffEntry]:
    out: list[DiffEntry] = []
    for cid, now in sorted(curr.items()):
        was = prev.get(cid)
        if was is None or was.get("status") == now.get("status"):
            continue
        if now.get("status") == "open":
            continue
        out.append(DiffEntry(
            type="conflict_resolved", subject=cid,
            before=was.get("status"), after=now.get("status"),
            detail={"kind": now.get("kind"),
                    "conceding_chair": now.get("conceding_chair")}))
    return out


def _parameter_entries(prev: dict, curr: dict) -> list[DiffEntry]:
    out: list[DiffEntry] = []
    for name, now in sorted(curr.items()):
        was = prev.get(name)
        if was is None or was.get("provenance") == now.get("provenance"):
            continue
        out.append(DiffEntry(
            type="parameter_provenance_change", subject=name,
            before=was.get("provenance"), after=now.get("provenance"),
            detail={"value_before": was.get("value"), "value_after": now.get("value")}))
    return out


def _breakpoint_entries(prev: dict, curr: dict) -> list[DiffEntry]:
    out: list[DiffEntry] = []
    for name, now in sorted(curr.items()):
        was = prev.get(name)
        if was is None or was == now:
            continue
        out.append(DiffEntry(type="breakpoint_moved", subject=name,
                             before=was, after=now, detail={}))
    return out


def _confidence_entry(prev: dict, curr: dict) -> list[DiffEntry]:
    if prev.get("total") == curr.get("total"):
        return []
    moved = [c for c in _COMPONENTS if prev.get(c) != curr.get(c)]
    return [DiffEntry(type="confidence_change", subject="evidence_confidence",
                      before=prev.get("total"), after=curr.get("total"),
                      detail={"components_moved": moved})]


def _verdict_entry(prev: Any, curr: Any) -> list[DiffEntry]:
    if prev == curr:
        return []
    return [DiffEntry(type="verdict_change", subject="verdict",
                      before=prev, after=curr, detail={})]


def compute_diff(previous: dict | None, current: dict) -> list[DiffEntry]:
    """Typed causal delta against the prior version. Empty for version 1."""
    if previous is None:
        return []

    entries: list[DiffEntry] = []
    entries += _assumption_entries(previous.get("assumptions", {}),
                                   current.get("assumptions", {}))
    entries += _evidence_entry(previous.get("evidence_counts", {}),
                               current.get("evidence_counts", {}))
    entries += _conflict_entries(previous.get("conflicts", {}),
                                 current.get("conflicts", {}))
    entries += _parameter_entries(previous.get("parameters", {}),
                                  current.get("parameters", {}))
    entries += _breakpoint_entries(previous.get("breakpoints", {}),
                                   current.get("breakpoints", {}))
    entries += _confidence_entry(previous.get("confidence", {}),
                                 current.get("confidence", {}))
    entries += _verdict_entry(previous.get("verdict"), current.get("verdict"))

    entries.sort(key=lambda e: (DIFF_ORDER.index(e.type), str(e.subject)))
    return entries


def causal_sentence(entries: list[DiffEntry]) -> str:
    """Render the chain as one sentence path (PRD §7.10 worked example).

    Deliberately not a bullet list: the point of the return visit is that one
    thing caused another, and a list hides causality.
    """
    if not entries:
        return ""

    by_type: dict[str, DiffEntry] = {}
    for e in entries:
        by_type.setdefault(e.type, e)

    parts: list[str] = []

    status = by_type.get("assumption_status_change")
    if status:
        name = status.detail.get("statement") or status.subject
        parts.append(f"{name} moved {status.before} → {status.after}")

    param = by_type.get("parameter_provenance_change")
    if param:
        clause = (f"which moved {param.subject} from {param.before} "
                  f"{param.detail.get('value_before')} to {param.after} "
                  f"{param.detail.get('value_after')}")
        parts.append(clause if parts else clause.replace("which moved ", "", 1).capitalize())

    bp = by_type.get("breakpoint_moved")
    if bp:
        parts.append(f"which moved the break-even {bp.subject.replace('_', ' ')} "
                     f"from {bp.before} to {bp.after}")

    conf = by_type.get("confidence_change")
    if conf and not (status or param or bp):
        moved = ", ".join(conf.detail.get("components_moved", []))
        parts.append(f"Evidence Confidence moved {conf.before} → {conf.after} "
                     f"({moved})")

    verdict = by_type.get("verdict_change")
    sentence = ", ".join(parts)
    if verdict:
        tail = f"Verdict changed {verdict.before} → {verdict.after}"
        sentence = f"{sentence}. {tail}" if sentence else tail

    return sentence.strip().rstrip(".") + "."
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/engines/test_diff.py -v
```
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/engines/diff.py apps/api/tests/engines/test_diff.py
git commit -m "feat(engines): typed ledger diff with single-sentence causal chain"
```

---

### Task 1.9: Engine purity guard and phase gate

**Files:**
- Create: `apps/api/tests/engines/test_purity.py`
- Create: `docs/SCORING.md`

**Why:** spec §6's boundary is only real if a test enforces it. Without this, a later phase will "just import the db client here" and the 100%-deterministic claim quietly dies.

- [ ] **Step 1: Write the guard test**

`apps/api/tests/engines/test_purity.py`:
```python
"""Spec §6: engines/ imports only schemas/. This test is the boundary."""
import ast
import pathlib

ENGINES = pathlib.Path(__file__).parents[2] / "jury" / "engines"
ALLOWED_INTERNAL = ("jury.schemas", "jury.engines")
BANNED_MODULES = (
    "httpx", "requests", "psycopg", "sqlalchemy", "litellm", "openai",
    "redis", "boto3", "fastapi", "langgraph", "jury.db", "jury.llm",
    "jury.retrieval", "jury.chairs", "jury.graph", "jury.api", "jury.settings",
)


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_every_engine_module_is_pure():
    files = sorted(ENGINES.rglob("*.py"))
    assert files, "no engine modules found"
    for path in files:
        for mod in _imports(path):
            for banned in BANNED_MODULES:
                assert not (mod == banned or mod.startswith(banned + ".")), \
                    f"{path.name} imports {mod}; engines must stay pure (spec §6)"


def test_engines_import_no_internal_module_other_than_schemas():
    for path in sorted(ENGINES.rglob("*.py")):
        for mod in _imports(path):
            if mod.startswith("jury."):
                assert mod.startswith(ALLOWED_INTERNAL), f"{path.name} imports {mod}"


def test_no_engine_reads_the_environment():
    """A pure function does not consult os.environ."""
    for path in sorted(ENGINES.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "os.environ" not in src and "getenv" not in src, path.name
```

- [ ] **Step 2: Run the whole engine suite**

```bash
cd apps/api && uv run pytest tests/engines -q
```
Expected: all green. If `test_purity.py` fails, **fix the engine, not the test.**

- [ ] **Step 3: Write `docs/SCORING.md`**

Publish, verbatim and with provenance: tier weights, the tier-4 override table, the strength formula, the status table, the four confidence components with the `0.30/0.30/0.20/0.20` split, the gate conditions, and R1–R5 with their exact thresholds (`±10%`, `>25%`).

Include this sentence explicitly, per spec §26.3:

> The 0.30 / 0.30 / 0.20 / 0.20 split was **chosen by judgement, not fitted to data.** It is published here so that it can be argued with.

- [ ] **Step 4: Run the full suite and record the gate**

```bash
cd apps/api && uv run pytest -q
```

- [ ] **Step 5: Append to `CHANGELOG.md` and push**

Record the actual test count, the PRD §19.2 rows now at 100%, and the two deviations noted in this phase (R4 criticality set; missing `ad_consumer`/`hardware` templates mapping to nearest).

```bash
git add -A
git commit -m "test(engines): purity boundary guard; docs: publish scoring model"
git push origin main
```

---

## Phase 1 exit criteria

- [ ] `scopes_overlap` and `covers_target` pass the full enum matrix — symmetric, reflexive, directional where required
- [ ] `dedup_hash` stable across tracking-parameter variants; period excluded
- [ ] `strength` agrees with hand-computed `tanh(|raw|/2)` on mixed tiers
- [ ] Tier-4 WTP override active and never widening tier-4 influence
- [ ] `evidence_confidence` returns the total **and** all four components
- [ ] **288-combination brute force proves `PROCEED`/`STOP` unreachable below threshold**
- [ ] R1–R5 fire exactly on their conditions and not otherwise; thresholds exactly ±10% and >25%
- [ ] R3 always triggers cross-examination regardless of criticality
- [ ] R5 reports a gap, not a contradiction
- [ ] Economics agrees **exactly** with hand-computed fixtures for marketplace and saas
- [ ] `brentq` breakpoints exact to 1e-6; no NaN, no fabricated thresholds
- [ ] Sensitivity ranked descending and carries provenance
- [ ] Experiments filter to `founder_asserted` and every one has a non-null `criterion_spec`
- [ ] Retention maps to `documented_proxy` with a stated limitation
- [ ] Kill-criterion evaluation 100% across every comparator
- [ ] Diff renders the PRD §7.10 causal chain as a single sentence
- [ ] **Purity guard green** — no engine imports I/O, a client, or `settings`
- [ ] `docs/SCORING.md` published, stating the weights were chosen not fitted
