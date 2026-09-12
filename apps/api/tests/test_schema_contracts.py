import pytest
from pydantic import ValidationError

from jury.schemas.claim import ClaimRecord
from jury.schemas.enums import Chair, Direction, Geo, Segment
from jury.schemas.experiment import CriterionSpec
from jury.schemas.scope import Scope

VALID = {
    "assumption_id": None,
    "new_assumption": {"statement": "SMBs in India pay above 149 INR per month for this.",
                       "class_key": "saas.wtp_above_cost"},
    "direction": "supports",
    "variable": "price_monthly",
    "value_num": 149.0,
    "unit": "INR_per_month",
    "scope": {"geo": "IN", "segment": "smb", "tier": "entry", "period": "2026"},
    "confidence": 0.8,
    "source_url": "https://example.test/pricing",
    "source_tier": 1,
    "excerpt": "Starter plan is priced at 149 INR per month.",
    "chair": "market",
}


def test_valid_claim_parses():
    c = ClaimRecord.model_validate(VALID)
    assert c.chair is Chair.MARKET
    assert c.direction is Direction.SUPPORTS
    assert c.scope.geo is Geo.IN


def test_tier_five_claim_is_rejected():
    """P1: a model prior is not evidence and must not survive parsing."""
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"source_tier": 5})


def test_excerpt_over_240_chars_rejected():
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"excerpt": "x" * 241})


def test_non_http_source_url_rejected():
    """SSRF surface: target URLs are partly model-selected (PRD §17.4)."""
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"source_url": "file:///etc/passwd"})


def test_claim_needs_either_assumption_id_or_new_assumption():
    bad = dict(VALID)
    bad["new_assumption"] = None
    bad["assumption_id"] = None
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(bad)


def test_value_range_must_be_ordered():
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"value_min": 100.0, "value_max": 50.0})


def test_free_text_scope_is_rejected():
    """PRD §12.1: a free-text scope is uncomparable and would break the conflict engine."""
    with pytest.raises(ValidationError):
        Scope.model_validate({"geo": "India", "segment": "smb"})


def test_criterion_spec_requires_machine_evaluable_comparator():
    spec = CriterionSpec.model_validate(
        {"metric": "prepay_count", "comparator": ">=", "threshold": 4, "n": 20})
    assert spec.threshold == 4
    with pytest.raises(ValidationError):
        CriterionSpec.model_validate(
            {"metric": "vibes", "comparator": "feels better", "threshold": 4})


def test_settings_tolerate_a_completely_empty_env(monkeypatch):
    """Spec §3: the build must be verifiable before any credential exists."""
    for k in ("GROQ_API_KEY", "BRAVE_API_KEY", "SUPABASE_SERVICE_ROLE_KEY",
              "UPSTASH_REDIS_REST_URL", "EXA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from jury.settings import Settings
    s = Settings()
    assert s.groq_api_key is None
    assert s.offline is True          # defaults to offline when unkeyed
