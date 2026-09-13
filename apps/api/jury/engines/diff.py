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
    """Typed causal delta against the prior version. Empty for version 1.

    Every per-field helper iterates `sorted(dict.items())`, so ordering is
    determined by key/type, never by caller-supplied dict insertion order.
    """
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

    Each clause after the first is prefixed with "which" to read as a causal
    chain; the leading clause (whichever fires first) is rendered standalone,
    capitalised on its own first letter only -- not via str.capitalize(),
    which would also lower-case the rest of the clause and corrupt a
    snake_case variable name such as price_monthly into Price_monthly.
    """
    if not entries:
        return ""

    by_type: dict[str, DiffEntry] = {}
    for e in entries:
        by_type.setdefault(e.type, e)

    def _lead(clause: str) -> str:
        return clause[0].upper() + clause[1:] if clause else clause

    parts: list[str] = []

    status = by_type.get("assumption_status_change")
    if status:
        name = status.detail.get("statement") or status.subject
        parts.append(f"{name} moved {status.before} → {status.after}")

    param = by_type.get("parameter_provenance_change")
    if param:
        clause = (f"moved {param.subject} from {param.before} "
                  f"{param.detail.get('value_before')} to {param.after} "
                  f"{param.detail.get('value_after')}")
        parts.append(f"which {clause}" if parts else _lead(clause))

    bp = by_type.get("breakpoint_moved")
    if bp:
        clause = (f"moved the break-even {bp.subject.replace('_', ' ')} "
                  f"from {bp.before} to {bp.after}")
        parts.append(f"which {clause}" if parts else _lead(clause))

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
