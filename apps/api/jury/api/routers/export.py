"""Markdown case-file export. Task 6.6. PRD §4, §7.10, §9, §16.8, §23.

F15's PDF is cut (spec §4); Markdown is retained because it is cheap and it
carries the citations, which is the point -- PRD §23: "Every claim in the
output is clickable and verifiable." Every evidence item's source URL is
rendered as a literal, clickable link, never paraphrased away.

P9 ("required non-null field before the plan can be exported") is enforced
here, at the export boundary, exactly as PRD §4 specifies: an experiment
whose `kill_criterion` is empty refuses the whole export with 409, rather
than silently omitting that one experiment's criterion from the document --
a founder who can export a plan missing a kill criterion is a founder who can
rationalise an ambiguous result later, which is the exact failure P9 exists
to prevent.

Ownership is RLS via `get_user_pool`, the same pattern as every other
project-scoped route (`versions.py`, `runs.py`): a project another user owns
is invisible, not merely forbidden, so it 404s rather than 403ing.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from jury.api.deps import get_user_pool
from jury.db.repositories import (
    AssumptionClassRepo,
    AssumptionRepo,
    ConflictRepo,
    EvidenceRepo,
    ExperimentRepo,
    LedgerVersionRepo,
    ModelRunRepo,
    ProjectRepo,
    VerdictRepo,
)
from jury.engines.scoring import CONFIDENCE_WEIGHTS
from jury.graph.nodes.coverage import coverage_gaps

router = APIRouter(tags=["export"])


class ExportIn(BaseModel):
    format: str = "md"


async def _latest_pitch(pool, project_id: str) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select body from pitches where project_id = %s "
                "order by created_at desc limit 1", (project_id,))
            row = await cur.fetchone()
            return row[0] if row else ""


def _fmt(value) -> str:
    return "n/a" if value is None else str(value)


def _deltas_by_conflict(deltas: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in deltas:
        out.setdefault(str(d["conflict_id"]), []).append(d)
    return out


def build_case_file_markdown(*, project: dict, pitch: str, assumptions: list[dict],
                             gaps: list[dict], evidence: list[dict],
                             conflicts: list[dict], deltas_by_conflict: dict,
                             model_run: dict | None, verdict: dict | None,
                             experiments: list[dict], versions: list[dict]) -> str:
    """Pure formatter: every argument is data the route has already fetched
    and P9-checked; this function never touches the database and never
    raises, so it is trivially unit-testable in isolation from the route's
    auth/gating concerns if a future test wants that."""
    lines: list[str] = [f"# {project.get('name') or 'Case File'}", ""]

    lines += ["## Pitch", pitch or "_no pitch recorded_", ""]
    lines += [f"## Archetype: {project.get('archetype') or 'undetected'}", ""]

    lines.append("## Assumptions")
    if assumptions:
        for a in assumptions:
            lines.append(f"- **{a['statement']}** — status: {a['status']}, "
                         f"strength: {_fmt(a.get('strength'))} ({a['origin']}, "
                         f"{a['criticality']})")
    else:
        lines.append("_no assumptions recorded_")
    lines.append("")

    lines.append("## Coverage Gaps")
    if gaps:
        for g in gaps:
            lines.append(f"- {g['question']} (weight {g['crit_weight']})")
    else:
        lines.append("_no gaps against the archetype checklist_")
    lines.append("")

    lines.append("## Evidence")
    if evidence:
        by_chair: dict[str, list[dict]] = {}
        for e in evidence:
            by_chair.setdefault(e["chair"], []).append(e)
        for chair, items in sorted(by_chair.items()):
            lines.append(f"### {chair.title()}")
            for e in items:
                label = e.get("variable") or "evidence"
                lines.append(f"- [{label}]({e['source_url']}) — tier {e['source_tier']}, "
                             f"{e['direction']}, confidence {_fmt(e.get('confidence'))}")
    else:
        lines.append("_no evidence gathered_")
    lines.append("")

    lines.append("## Conflicts")
    if conflicts:
        for c in conflicts:
            lines.append(f"- {c['kind']} conflict ({c['severity']}) — {c['status']}")
            for d in deltas_by_conflict.get(str(c["id"]), []):
                lines.append(f"  - {d['chair']}: {d['before']} → {d['after']} "
                             f"({d['reason']})")
    else:
        lines.append("_no conflicts raised_")
    lines.append("")

    lines.append("## Economics")
    if model_run:
        lines.append("### Parameters")
        for name, p in sorted((model_run.get("parameters") or {}).items()):
            lines.append(f"- {name}: {_fmt(p.get('value'))} {p.get('unit') or ''} "
                         f"— provenance: {p.get('provenance')}")
        lines.append("### Breakpoints")
        for b in model_run.get("breakpoints") or []:
            lines.append(f"- {b.get('sentence')}")
    else:
        lines.append("_no economics computed_")
    lines.append("")

    lines.append("## Verdict")
    if verdict:
        components = verdict.get("components") or {}
        lines.append(f"**Decision: {verdict['decision']}** "
                     f"(Evidence Confidence: {_fmt(verdict.get('evidence_confidence'))})")
        lines.append(f"- coverage: {_fmt(components.get('coverage'))}")
        lines.append(f"- mean_strength: {_fmt(components.get('mean_strength'))}")
        lines.append(f"- contradiction: {_fmt(components.get('contradiction'))}")
        lines.append(f"- open_critical: {_fmt(components.get('open_critical'))}")
        lines.append(
            "- formula: confidence = "
            f"{CONFIDENCE_WEIGHTS['coverage']:.0%} × coverage + "
            f"{CONFIDENCE_WEIGHTS['mean_strength']:.0%} × mean_strength + "
            f"{CONFIDENCE_WEIGHTS['contradiction']:.0%} × (1 − contradiction) + "
            f"{CONFIDENCE_WEIGHTS['open_critical']:.0%} × (1 − open_critical)")
    else:
        lines.append("_no verdict yet_")
    lines.append("")

    lines.append("## Experiments")
    if experiments:
        for e in experiments:
            lines.append(f"- **{e['method']}** ({e['status']}) — kill criterion: "
                         f"{e['kill_criterion']}")
    else:
        lines.append("_no experiments proposed_")
    lines.append("")

    lines.append("## Version History")
    if versions:
        for v in versions:
            lines.append(f"- v{v['version']} — {v['created_at']}")
    else:
        lines.append("_no versions written yet_")

    return "\n".join(lines) + "\n"


@router.post("/projects/{project_id}/export")
async def export_project(project_id: str, body: ExportIn, pool=Depends(get_user_pool)):
    project = await ProjectRepo(pool).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if body.format != "md":
        raise HTTPException(status_code=400, detail="only the 'md' export format is supported")

    experiments = await ExperimentRepo(pool).list_for_project(project_id)
    if any(not e.get("kill_criterion") for e in experiments):
        # P9, enforced at the export boundary (PRD §4): a plan with an
        # experiment missing its pre-registered kill criterion may not be
        # exported at all -- there is no partial export that drops the
        # offending experiment silently.
        raise HTTPException(
            status_code=409,
            detail="every experiment must carry a kill criterion before export")

    pitch = await _latest_pitch(pool, project_id)
    assumptions = await AssumptionRepo(pool).list_for_project(project_id)
    classes = (await AssumptionClassRepo(pool).list_for_archetype(project["archetype"])
              if project.get("archetype") else [])
    gaps = coverage_gaps(classes, assumptions)
    evidence = await EvidenceRepo(pool).list_for_project_with_tier(project_id)
    conflicts = await ConflictRepo(pool).list_for_project(project_id)
    deltas = await ConflictRepo(pool).list_deltas([str(c["id"]) for c in conflicts])
    model_runs = await ModelRunRepo(pool).list_for_project(project_id)
    verdicts = await VerdictRepo(pool).list_for_project(project_id)
    versions = await LedgerVersionRepo(pool).list_for_project(project_id)

    markdown = build_case_file_markdown(
        project=project, pitch=pitch, assumptions=assumptions, gaps=gaps,
        evidence=evidence, conflicts=conflicts,
        deltas_by_conflict=_deltas_by_conflict(deltas),
        model_run=model_runs[-1] if model_runs else None,
        verdict=verdicts[-1] if verdicts else None,
        experiments=experiments, versions=versions)

    return Response(content=markdown, media_type="text/markdown")
