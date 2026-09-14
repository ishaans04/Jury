"""Versions and causal-diff read routes. Task 6.5. PRD §7.10, §9, §16.8.

"The return visit UI shows the diff, not a new report" (PRD §7.10) -- these
two routes are the entire read surface a return-visit screen needs: the list
of immutable ledger versions for a project, and the typed causal diff plus a
one-sentence causal chain for any one of them against its predecessor.

Both routes are pure reads over `LedgerVersionRepo` (Task 6.2); neither ever
recomputes a diff -- `ledger_versions.diff` was computed once, at write time,
by `jury.graph.nodes.version.write_version`, and is served back verbatim
here. `causal_sentence`, though, is NOT stored (there is no `sentence`
column) -- it is cheap and pure (`jury.engines.diff.causal_sentence`, no
model call, fully reproducible from the stored diff), so it is rendered on
every read from the stored `diff` rather than persisted redundantly. Ownership
is enforced the same way every other project-scoped route enforces it: RLS
via `get_user_pool`'s user-scoped connection makes another user's project
(and its versions, which cascade from `project_id` through the same RLS
policy) invisible, not merely inaccessible -- a missing project or a version
that belongs to someone else's project both surface as 404, never a leaked
403 that would confirm the project's existence to a non-owner.
"""
from fastapi import APIRouter, Depends, HTTPException

from jury.api.deps import get_user_pool
from jury.db.repositories import LedgerVersionRepo, ProjectRepo
from jury.engines.diff import DiffEntry, causal_sentence

router = APIRouter(prefix="/projects/{project_id}", tags=["versions"])


def _version_out(row: dict) -> dict:
    out = dict(row)
    out["id"] = str(out["id"])
    out["project_id"] = str(out["project_id"])
    out["run_id"] = str(out["run_id"])
    return out


async def _owned_project(pool, project_id: str) -> dict:
    project = await ProjectRepo(pool).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/versions")
async def list_versions(project_id: str, pool=Depends(get_user_pool)):
    await _owned_project(pool, project_id)
    rows = await LedgerVersionRepo(pool).list_for_project(project_id)
    return [_version_out(r) for r in rows]


@router.get("/versions/{version}/diff")
async def version_diff(project_id: str, version: int, pool=Depends(get_user_pool)):
    await _owned_project(pool, project_id)

    row = await LedgerVersionRepo(pool).get_by_version(project_id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")

    entries: list[dict] = row["diff"]  # already-serialised DiffEntry dicts
    sentence = causal_sentence([DiffEntry(**e) for e in entries])
    return {"entries": entries, "causal_sentence": sentence}
