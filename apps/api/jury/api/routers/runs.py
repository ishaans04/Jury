"""Run-control routes. Task 4.4. PRD §13.

Deliberately **no** `GET /projects/{id}/evidence` (or any evidence read
route) anywhere in this router or `projects.py`: PRD §13 says reads the
client can satisfy directly through `supabase-js` with RLS -- assumptions,
evidence, conflicts, verdicts, versions -- go direct, never through
FastAPI. This router owns writes and run control only: starting a run,
reading its status/trace, confirming the hearing, and cancelling.
"""
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from jury.api.deps import CurrentUser, get_app_pool, get_current_user, get_settings, get_user_pool
from jury.db.repositories import AssumptionClassRepo, ProjectRepo, RunRepo
from jury.graph.build import resume_hearing, run_initial
from jury.schemas.assumption import AssumptionDraft
from jury.settings import Settings
from jury.tracing.events import PostgresTraceSink
from jury.transport.factory import build_transports

router = APIRouter(tags=["runs"])


class HearingConfirm(BaseModel):
    assumptions: list[AssumptionDraft]


def _run_out(row: dict) -> dict:
    out = dict(row)
    out["id"] = str(out["id"])
    out["project_id"] = str(out["project_id"])
    out["user_id"] = str(out["user_id"])
    return out


async def _classes_for(pool, project_id: str) -> list[tuple[str, float, str]]:
    project = await ProjectRepo(pool).get(project_id)
    if project is None or not project.get("archetype"):
        return []
    return await AssumptionClassRepo(pool).list_for_archetype(project["archetype"])


@router.post("/projects/{project_id}/runs", status_code=202)
async def start_run(project_id: str, background_tasks: BackgroundTasks,
                    user: CurrentUser = Depends(get_current_user),
                    pool=Depends(get_user_pool), app_pool=Depends(get_app_pool),
                    app_settings: Settings = Depends(get_settings)):
    project = await ProjectRepo(pool).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    run_id = str(uuid4())
    row = await RunRepo(pool).create(project_id, user.id, thread_id=run_id, run_id=run_id)

    pitch_row = await _latest_pitch(pool, project_id)
    classes = await _classes_for(pool, project_id)
    transports = build_transports(app_settings)

    background_tasks.add_task(
        run_initial, project_id, run_id, pitch_row, project["target_scope"],
        transports=transports, pool=app_pool, classes=classes, settings=app_settings)

    return {"run_id": run_id, "status": row["status"]}


async def _latest_pitch(pool, project_id: str) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select body from pitches where project_id = %s "
                "order by created_at desc limit 1", (project_id,))
            row = await cur.fetchone()
            return row[0] if row else ""


@router.get("/runs/{run_id}")
async def get_run(run_id: str, pool=Depends(get_user_pool)):
    row = await RunRepo(pool).get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_out(row)


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, pool=Depends(get_user_pool)):
    row = await RunRepo(pool).get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return await RunRepo(pool).list_events(run_id)


@router.post("/runs/{run_id}/hearing/confirm", status_code=202)
async def confirm_hearing(run_id: str, body: HearingConfirm,
                          background_tasks: BackgroundTasks,
                          pool=Depends(get_user_pool), app_pool=Depends(get_app_pool),
                          app_settings: Settings = Depends(get_settings)):
    run = await RunRepo(pool).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    classes = await _classes_for(pool, str(run["project_id"]))
    transports = build_transports(app_settings)
    edited = [a.model_dump(mode="json") for a in body.assumptions]
    # The project row is authoritative for archetype: the founder may have
    # corrected it in the hearing (PATCH /projects/{id}) after detection.
    project = await ProjectRepo(pool).get(str(run["project_id"]))

    background_tasks.add_task(
        resume_hearing, run_id, edited, transports=transports, pool=app_pool,
        classes=classes, settings=app_settings,
        archetype=project.get("archetype") if project else None)

    return {"run_id": run_id, "status": "investigating"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, pool=Depends(get_user_pool)):
    """PRD §13: 'Cancel; checkpoint retained.' Deliberately does NOT delete
    or touch the LangGraph checkpoint rows -- a cancelled run's state stays
    resumable, only the run row's own bookkeeping records the cancellation.
    No CHECK-constrained `runs.status` value means literally 'cancelled'
    (the allowed set is `pending|hearing|investigating|cross_exam|deciding|
    complete|failed`), so this endpoint writes no status. It does record an
    `interrupt` trace row on the run -- a cancel is a human-initiated
    interrupt -- so a cancelled-and-left run is distinguishable from a normal
    one in the F17 trace, without touching the still-resumable checkpoint."""
    row = await RunRepo(pool).get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    await PostgresTraceSink(pool, run_id).emit(
        node="cancel", event="interrupt",
        detail={"reason": "cancel requested by user"})
    return _run_out(row)
