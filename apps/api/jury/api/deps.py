"""FastAPI dependencies. Task 4.4. PRD §13.

Every route but `/health` requires a Supabase-issued JWT. `get_current_user`
is the one place that JWT is ever decoded; every route depends on it
(directly or via `get_user_pool`) rather than re-implementing the check.
"""
import time
from dataclasses import dataclass

import httpx

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from psycopg_pool import AsyncConnectionPool

from jury.db.pool import get_pool, user_scoped_connection
from jury.settings import Settings, settings
from jury.transport.factory import build_transports
from jury.transport.protocols import Transports

_ALGORITHM = "HS256"
_ASYMMETRIC = {"ES256", "RS256"}
_JWKS_TTL_S = 600
_JWKS_MIN_REFRESH_S = 30
_jwks_cache: dict = {"keys": {}, "fetched_at": 0.0}
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


async def _fetch_jwks(supabase_url: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=5) as client:
        res = await client.get(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")
        res.raise_for_status()
        return res.json().get("keys", [])


async def _signing_key(app_settings: Settings, kid: str | None) -> dict | None:
    """The project's public signing key for `kid`, from Supabase's JWKS
    endpoint, cached. An unknown `kid` forces a refresh (rate-limited), so a
    key rotation is picked up without a restart."""
    if not app_settings.supabase_url or not kid:
        return None
    age = time.monotonic() - _jwks_cache["fetched_at"]
    if age > _JWKS_TTL_S or (kid not in _jwks_cache["keys"] and age > _JWKS_MIN_REFRESH_S):
        try:
            keys = await _fetch_jwks(app_settings.supabase_url)
        except (httpx.HTTPError, ValueError):
            return _jwks_cache["keys"].get(kid)
        _jwks_cache["keys"] = {k["kid"]: k for k in keys if "kid" in k}
        _jwks_cache["fetched_at"] = time.monotonic()
    return _jwks_cache["keys"].get(kid)


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
    Supabase JWT"). Current Supabase signs user sessions with an asymmetric
    key (ES256) instead, so those tokens are verified against the project's
    public JWKS; the algorithm is pinned to the kind of key that verifies
    it, never taken from the token alone."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid token")
    alg = header.get("alg")

    if alg == _ALGORITHM:
        if not app_settings.supabase_jwt_secret:
            # No secret configured means no HS256 token can ever be verified
            # as genuine -- refusing is the only safe default, never
            # "accept anything since we can't check."
            raise HTTPException(status_code=401, detail="JWT verification not configured")
        key = app_settings.supabase_jwt_secret
    elif alg in _ASYMMETRIC:
        key = await _signing_key(app_settings, header.get("kid"))
        if key is None or key.get("alg", alg) != alg:
            raise HTTPException(status_code=401, detail="invalid token")
    else:
        raise HTTPException(status_code=401, detail="invalid token")

    try:
        claims = jwt.decode(token, key, algorithms=[alg], audience=_AUDIENCE)
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token carries no subject")
    return CurrentUser(id=str(sub), claims=claims)


def get_transports(app_settings: Settings = Depends(get_settings)) -> Transports:
    """Task 6.4: a dependency (rather than every route calling
    `build_transports` inline, the way `jury.api.routers.runs` does for its
    background-task path) so a test can override this one seam
    (`app.dependency_overrides[get_transports] = ...`) with counting fakes
    and assert on call counts -- the affected-only re-run's own tests need
    to prove zero new `transports.search` calls happen, which a fresh
    `FixtureSearchClient()` built inline could never let a test observe."""
    return build_transports(app_settings)


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
