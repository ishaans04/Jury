"""FastAPI app. Task 4.4. PRD §13.

Every router but `health` carries `get_current_user` as a router-level
dependency (not just a route-local one): FastAPI resolves router-level
dependencies before parsing/validating the request body, so a request with
no token gets its 401 before an invalid or missing body could otherwise
surface as a 422 first -- the ordering the batch's own auth tests rely on
(`test_every_other_route_rejects_a_missing_token` sends a syntactically
empty `{}` body to every route, including ones whose real body schema would
itself reject `{}`).
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from jury.api.deps import get_current_user
from jury.api.routers import experiments, export, health, projects, runs, stream, versions
from jury.db.pool import close_pool, open_pool
from jury.settings import settings


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await open_pool(settings)
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(title="Jury Orchestrator", lifespan=_lifespan)

app.include_router(health.router)
app.include_router(projects.router, dependencies=[Depends(get_current_user)])
app.include_router(runs.router, dependencies=[Depends(get_current_user)])
app.include_router(experiments.router, dependencies=[Depends(get_current_user)])
app.include_router(stream.router, dependencies=[Depends(get_current_user)])
app.include_router(versions.router, dependencies=[Depends(get_current_user)])
app.include_router(export.router, dependencies=[Depends(get_current_user)])
