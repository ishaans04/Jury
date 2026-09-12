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
