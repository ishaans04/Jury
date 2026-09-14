"""The conditional cross-examination edge. Task 5.1. PRD §7.6, §16.4.

Debate is expensive (latency, tokens, theatre) and only earns its place where
a genuine conflict exists. This module decides, after `reconcile` has run the
deterministic conflict engine, whether the graph proceeds straight to
economics or first argues a bounded set of conflicts.

`state["conflicts"]` (as returned by `jury.graph.nodes.reconcile.run_reconcile`)
is a list of dicts, each carrying at minimum `id`, `kind`, `severity`,
`status`, and `triggers_cross_exam` -- the last of these mirrors
`jury.engines.conflict.DetectedConflict.triggers_cross_exam` exactly:
R3 (`founder_vs_world`) always trigger; R1/R2 (`chair_vs_chair`) trigger only
when the affected assumption's criticality is `blocking` or `high` (severity
`critical`/`high`, since `jury.engines.conflict._SEVERITY` maps criticality
to severity one-for-one); R4 (`no_evidence`) and R5 (`scope_gap`) never
trigger -- an absence is reported, not argued (F9).
"""
from typing import Literal

MAX_CROSS_EXAM_CONFLICTS = 5

# Lower number sorts first -- "criticality then severity" is the same axis
# here (PRD §16.3's severity is derived one-for-one from criticality), so one
# ordering satisfies both.
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_OPEN_STATUS = "open"
_FOUNDER_VS_WORLD = "founder_vs_world"


def _sort_key(conflict: dict) -> tuple[bool, int, str]:
    """R3 (`founder_vs_world`) leads at equal severity: it is the rule the
    whole product is built around (the founder's own claim losing to
    evidence), so if only one conflict can be argued, it must be that one."""
    return (
        conflict["kind"] != _FOUNDER_VS_WORLD,
        _SEVERITY_ORDER.get(conflict["severity"], len(_SEVERITY_ORDER)),
        conflict["id"],
    )


def select_conflicts_for_cross_exam(conflicts: list[dict]) -> list[dict]:
    """Deterministic selection: open + triggering conflicts only, ordered by
    `_sort_key`, capped at `MAX_CROSS_EXAM_CONFLICTS`. Already-resolved
    conflicts (status != "open") are never re-selected -- there is nothing
    left to argue about a conflict a prior round already settled."""
    eligible = [
        c for c in conflicts
        if c.get("status", _OPEN_STATUS) == _OPEN_STATUS and c.get("triggers_cross_exam")
    ]
    eligible.sort(key=_sort_key)
    return eligible[:MAX_CROSS_EXAM_CONFLICTS]


def route_after_reconcile(state: dict) -> Literal["cross_exam", "economics"]:
    """P7: debate only where conflict exists. No conflicts, or only
    non-triggering ones (R4/R5, or a sub-critical chair dispute), routes
    straight to economics -- not "debate, briefly, anyway"."""
    conflicts = state.get("conflicts") or []
    return "cross_exam" if select_conflicts_for_cross_exam(conflicts) else "economics"
