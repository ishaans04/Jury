"""FastAPI dependencies. Task 4.4. PRD §13.

Every route but `/health` requires a Supabase-issued JWT. `get_current_user`
is the one place that JWT is ever decoded; every route depends on it
(directly or via `get_user_pool`) rather than re-implementing the check.
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from psycopg_pool import AsyncConnectionPool

from jury.db.pool import get_pool, user_scoped_connection
from jury.settings import Settings, settings

_ALGORITHM = "HS256"
_AUDIENCE = "authenticated"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    claims: dict


def get_settings() -> Settings:
    return settings


def get_app_pool(app_settings: Settings = Depends(get_settings)) -> AsyncConnectionPool:
    """The plain, unrestricted pool -- used by the graph pipeline itself
    (jury.graph.build), which is not tied to one HTTP request's identity."""
    return get_pool(app_settings)


async def get_current_user(
    authorization: str | None = Header(default=None),
    app_settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validates the bearer JWT against `settings.supabase_jwt_secret`
    (HS256, `audience="authenticated"` -- the same claim Supabase's own
    PostgREST layer checks). Rejects a missing header, a malformed token, a
    token signed with the wrong secret, and an expired token identically --
    all four are `python-jose` raising `JWTError` from `jwt.decode`, and all
    four must produce the same 401 (PRD §13: "every route requires a
    Supabase JWT")."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    if not app_settings.supabase_jwt_secret:
        # No secret configured means no token can ever be verified as
        # genuine -- refusing everything is the only safe default, never
        # "accept anything since we can't check."
        raise HTTPException(status_code=401, detail="JWT verification not configured")

    try:
        claims = jwt.decode(token, app_settings.supabase_jwt_secret,
                            algorithms=[_ALGORITHM], audience=_AUDIENCE)
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token carries no subject")
    return CurrentUser(id=str(sub), claims=claims)


async def get_user_pool(
    user: CurrentUser = Depends(get_current_user),
    pool: AsyncConnectionPool = Depends(get_app_pool),
):
    """Yields a connection switched to `authenticated` for this request's
    user (`jury.db.pool.user_scoped_connection`), so every repository call a
    route makes through it is subject to RLS exactly as PRD §13 requires:
    "writes under the user's ID so RLS applies to service-side writes too."
    """
    async with user_scoped_connection(pool, user.id) as scoped:
        yield scoped
