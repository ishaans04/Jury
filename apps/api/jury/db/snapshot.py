"""Ledger snapshot builder. Task 6.1. PRD §9, §16.8.

Jury is not a report generator -- a regenerated report is explicitly a
failure mode (PRD §2.2). Instead the ledger *versions and diffs*: each run
writes an immutable snapshot (this module) plus a computed causal delta
against the previous one (`jury.engines.diff.compute_diff`, reused verbatim
here, never reimplemented).

`build_snapshot` assembles a complete, self-contained `Snapshot` dict --
exactly the shape `compute_diff` consumes (see its own module docstring and
`DIFF_ORDER`): `assumptions`, `evidence_counts`, `conflicts`, `parameters`,
`breakpoints`, `confidence`, `verdict`.

Two things make this "immutable record" property hold, deliberately, at
every field:

  1. Self-containment. `ledger_versions.snapshot` is a jsonb column read back
     with no join to any live table -- a schema change years from now (a
     renamed column, a dropped table) must not make an old version
     unreadable. So every field below carries the DATA a reader needs
     (an assumption's `statement` text, not just its id), never a bare
     foreign key a reader would have to look up elsewhere to make sense of.

  2. JSON-serialisability at the boundary. Postgres numeric columns come
     back from psycopg as `Decimal`, and every id column as `uuid.UUID` --
     both raise inside `json.dumps` (and inside the `jsonb` write
     `LedgerVersionRepo.create_next_version` does via `Json(...)`). Every
     numeric is cast to `float` and every id/uuid to `str` here, at the one
     place data crosses from "live Postgres row" to "snapshot dict",
     instead of leaving that to whichever caller happens to serialise it
     later.

Scope, per field (`run_id` selects the run-specific rollups; everything else
is cumulative across the whole project's history -- a return-visit run must
not forget evidence, assumptions or conflicts an earlier run already
produced):

  - `assumptions`, `evidence_counts`, `conflicts`: cumulative, whole project.
  - `parameters`, `breakpoints`, `confidence`, `verdict`: this run's own
    model_run / verdict rows (the ones economics/jury just wrote).

Two builds of an unchanged ledger must be byte-for-byte identical (every
per-field dict below is built by iterating rows in a stable, deterministic
order -- `ORDER BY created_at` at the SQL layer, and Python dict insertion
order for anything grouped in Python), or every future version would diff
against itself and produce pure noise in the causal chain the return-visit
screen renders.
"""
from jury.db.repositories import (
    AssumptionRepo,
    ConflictRepo,
    EvidenceRepo,
    ModelRunRepo,
    VerdictRepo,
)


def _num(value) -> float | None:
    """Decimal -> float at the boundary; None passes through unchanged."""
    return None if value is None else float(value)


async def _assumptions(pool, project_id: str) -> dict:
    rows = await AssumptionRepo(pool).list_for_project(project_id)
    return {
        str(a["id"]): {
            "statement": a["statement"],
            "status": a["status"],
            "origin": a["origin"],
            "discovered_by": a["discovered_by"],
            "criticality": a["criticality"],
        }
        for a in rows
    }


async def _evidence_counts(pool, project_id: str) -> dict:
    rows = await EvidenceRepo(pool).list_for_project_with_tier(project_id)
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        by_tier = counts.setdefault(row["chair"], {})
        tier_key = str(row["source_tier"])
        by_tier[tier_key] = by_tier.get(tier_key, 0) + 1
    return counts


async def _conflicts(pool, project_id: str) -> dict:
    conflict_rows = await ConflictRepo(pool).list_for_project(project_id)
    conflict_ids = [str(c["id"]) for c in conflict_rows]
    deltas = await ConflictRepo(pool).list_deltas(conflict_ids)
    deltas_by_conflict: dict[str, list[dict]] = {}
    for d in deltas:
        deltas_by_conflict.setdefault(str(d["conflict_id"]), []).append(d)

    out: dict = {}
    for c in conflict_rows:
        cid = str(c["id"])
        conceding_chair = None
        cds = deltas_by_conflict.get(cid)
        if cds:
            conceding_chair = cds[-1]["chair"]
        out[cid] = {
            "status": c["status"],
            "kind": c["kind"],
            "severity": c["severity"],
            "conceding_chair": conceding_chair,
        }
    return out


async def _latest_model_run(pool, project_id: str, run_id: str) -> dict | None:
    rows = [r for r in await ModelRunRepo(pool).list_for_project(project_id)
           if str(r["run_id"]) == str(run_id)]
    if not rows:
        return None
    return rows[-1]   # list_for_project orders by created_at ascending


async def _latest_verdict(pool, project_id: str, run_id: str) -> dict | None:
    rows = [r for r in await VerdictRepo(pool).list_for_project(project_id)
           if str(r["run_id"]) == str(run_id)]
    if not rows:
        return None
    return rows[-1]


def _parameters(model_run: dict | None) -> dict:
    if model_run is None:
        return {}
    params = model_run["parameters"] or {}
    return {
        name: {
            "value": _num(p.get("value")),
            "unit": p.get("unit"),
            "provenance": p.get("provenance"),
            "source_id": str(p["source_id"]) if p.get("source_id") is not None else None,
            "assumption_id": (str(p["assumption_id"])
                              if p.get("assumption_id") is not None else None),
        }
        for name, p in params.items()
    }


def _breakpoints(model_run: dict | None) -> dict:
    """`model_runs.breakpoints` is stored as a bare LIST (jury/graph/nodes/
    economics.py: `[b.model_dump(mode='json') for b in result.breakpoints]`)
    -- `compute_diff`'s `_breakpoint_entries` needs a dict keyed by
    variable (`for name, now in sorted(curr.items())`), so the list is
    re-keyed here rather than handed through as-is."""
    if model_run is None:
        return {}
    return {
        b["variable"]: {
            "threshold": _num(b.get("threshold")),
            "direction": b.get("direction"),
            "unit": b.get("unit"),
            "output": b.get("output"),
            "sentence": b.get("sentence"),
        }
        for b in (model_run["breakpoints"] or [])
    }


def _confidence(verdict_row: dict | None) -> dict:
    if verdict_row is None:
        return {"total": None, "coverage": None, "mean_strength": None,
               "contradiction": None, "open_critical": None}
    components = verdict_row["components"] or {}
    return {
        "total": _num(verdict_row["evidence_confidence"]),
        "coverage": _num(components.get("coverage")),
        "mean_strength": _num(components.get("mean_strength")),
        "contradiction": _num(components.get("contradiction")),
        "open_critical": _num(components.get("open_critical")),
    }


async def build_snapshot(pool, project_id: str, run_id: str) -> dict:
    """Assembles the complete, self-contained `Snapshot` dict `compute_diff`
    consumes, from the live ledger. See the module docstring for the
    self-containment and JSON-serialisability guarantees this must hold."""
    model_run = await _latest_model_run(pool, project_id, run_id)
    verdict_row = await _latest_verdict(pool, project_id, run_id)

    return {
        "assumptions": await _assumptions(pool, project_id),
        "evidence_counts": await _evidence_counts(pool, project_id),
        "conflicts": await _conflicts(pool, project_id),
        "parameters": _parameters(model_run),
        "breakpoints": _breakpoints(model_run),
        "confidence": _confidence(verdict_row),
        "verdict": verdict_row["decision"] if verdict_row is not None else None,
    }
