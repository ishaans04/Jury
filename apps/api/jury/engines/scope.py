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
