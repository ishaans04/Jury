"""Project routes. Task 4.4. PRD §13.

`POST /projects` is the only route that makes an LLM call directly (a single
archetype-detection pass, not the full graph) -- PRD §13: "Create project
from a pitch; returns detected archetype + confidence." Everything after
that (extraction, the hearing, investigation) only happens once a run is
started (`POST /projects/{id}/runs`, in `runs.py`).
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from jury.api.deps import CurrentUser, get_current_user, get_settings, get_user_pool
from jury.db.repositories import PitchRepo, ProjectRepo
from jury.graph.nodes.archetype import detect_archetype
from jury.schemas.enums import Archetype
from jury.schemas.scope import Scope
from jury.settings import Settings
from jury.transport.factory import build_transports

router = APIRouter(prefix="/projects", tags=["projects"])

_MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
_ARTIFACT_CHUNK_BYTES = 64 * 1024
_ALLOWED_ARTIFACT_MIME = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
})


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    pitch: str = Field(min_length=200, max_length=2000)
    target_scope: Scope


class ProjectPatch(BaseModel):
    name: str | None = None
    archetype: Archetype | None = None
    target_scope: Scope | None = None


def _project_out(row: dict, *, archetype_confidence: float | None = None) -> dict:
    out = dict(row)
    out["id"] = str(out["id"])
    out["user_id"] = str(out["user_id"])
    if archetype_confidence is not None:
        out["archetype_confidence"] = archetype_confidence
    return out


@router.post("", status_code=201)
async def create_project(body: ProjectCreate, user: CurrentUser = Depends(get_current_user),
                         pool=Depends(get_user_pool), app_settings: Settings = Depends(get_settings)):
    transports = build_transports(app_settings)
    report = await detect_archetype({"pitch": body.pitch}, transports=transports)
    archetype = report.get("archetype")
    confidence = report.get("archetype_confidence") or 0.0

    row = await ProjectRepo(pool).create(
        user.id, body.name, body.target_scope.model_dump(mode="json"), archetype=archetype)
    await PitchRepo(pool).create(str(row["id"]), body.pitch)

    return _project_out(row, archetype_confidence=confidence)


@router.get("")
async def list_projects(user: CurrentUser = Depends(get_current_user), pool=Depends(get_user_pool)):
    rows = await ProjectRepo(pool).list_for_user(user.id)
    return [_project_out(r) for r in rows]


@router.get("/{project_id}")
async def get_project(project_id: str, pool=Depends(get_user_pool)):
    row = await ProjectRepo(pool).get(project_id)
    if row is None:
        # RLS makes another user's project invisible rather than raising --
        # a query that matches zero rows and a project that never existed
        # are indistinguishable here by construction, so both surface as 404.
        raise HTTPException(status_code=404, detail="project not found")
    return _project_out(row)


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectPatch, pool=Depends(get_user_pool)):
    row = await ProjectRepo(pool).update(
        project_id,
        name=body.name,
        archetype=body.archetype.value if body.archetype is not None else None,
        target_scope=body.target_scope.model_dump(mode="json") if body.target_scope else None,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _project_out(row)


@router.post("/{project_id}/artifacts", status_code=201)
async def upload_artifact(project_id: str, file: UploadFile = File(...),
                          pool=Depends(get_user_pool)):
    row = await ProjectRepo(pool).get(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")

    if file.content_type not in _ALLOWED_ARTIFACT_MIME:
        raise HTTPException(status_code=415, detail=f"unsupported media type {file.content_type!r}")

    # Read in bounded chunks and abort the moment the cap is exceeded, so a
    # hostile multi-hundred-MB upload never buffers into memory. Only the size
    # is stored, so chunks are discarded as they are counted -- peak memory is
    # one chunk, not the whole body.
    size = 0
    while chunk := await file.read(_ARTIFACT_CHUNK_BYTES):
        size += len(chunk)
        if size > _MAX_ARTIFACT_BYTES:
            raise HTTPException(status_code=413, detail="artifact exceeds the 10 MB limit")

    await PitchRepo(pool).add_artifact(project_id, {
        "filename": file.filename, "content_type": file.content_type, "size": size,
    })
    return {"filename": file.filename, "size": size}
