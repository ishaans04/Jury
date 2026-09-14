"""Fixtures for the Task 4.4 FastAPI route tests.

Real Postgres is used for every fixture here, same as every other DB-backed
test package in this repo: a JWT's `sub` must name a row that actually
exists in `auth.users` (RLS's `auth.uid()` doesn't check this, but
`projects.user_id references auth.users(id)` does -- a project insert for a
JWT naming no real user would fail on the FK, not on RLS). Deleting the
`auth.users` row at teardown cascades through projects -> runs -> everything
else, so cleanup is a single delete per test user.
"""
import asyncio
import os
import sys
import time

import httpx
import psycopg
import pytest
from jose import jwt

from jury.api.main import app as _app
from jury.db.pool import close_pool, open_pool
from jury.settings import settings as app_settings

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
TEST_JWT_SECRET = "test-jwt-secret-for-jury-api-tests"


@pytest.fixture(scope="session", autouse=True)
def _configure_jwt_secret():
    app_settings.supabase_jwt_secret = TEST_JWT_SECRET
    yield


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


def _token(user_id: str, *, secret: str = TEST_JWT_SECRET, expired: bool = False) -> str:
    now = int(time.time())
    claims = {"sub": user_id, "role": "authenticated", "aud": "authenticated",
             "iat": now, "exp": now - 3600 if expired else now + 3600}
    return jwt.encode(claims, secret, algorithm="HS256")


async def _create_user() -> str:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into auth.users (instance_id, id, aud, role, email, "
            "encrypted_password, created_at, updated_at) "
            "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
            "'authenticated', 'authenticated', "
            "'api-' || gen_random_uuid() || '@test.local', '', now(), now()) "
            "returning id")
        user_id = (await cur.fetchone())[0]
    await conn.commit()
    await conn.close()
    return str(user_id)


async def _delete_user(user_id: str) -> None:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    async with conn.cursor() as cur:
        await cur.execute("delete from auth.users where id = %s", (user_id,))
    await conn.commit()
    await conn.close()


@pytest.fixture
def app():
    return _app


@pytest.fixture
async def client():
    """`httpx.ASGITransport` does not run the app's lifespan handlers on its
    own (unlike `TestClient`'s context manager), so the connection pool
    `jury.api.deps.get_app_pool` hands out is opened/closed here directly
    rather than relying on `jury.api.main`'s `_lifespan` (which real ASGI
    servers -- uvicorn -- do trigger)."""
    await open_pool(app_settings)
    transport = httpx.ASGITransport(app=_app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await close_pool()


@pytest.fixture
async def user_a():
    uid = await _create_user()
    yield uid
    await _delete_user(uid)


@pytest.fixture
async def user_b():
    uid = await _create_user()
    yield uid
    await _delete_user(uid)


@pytest.fixture
def auth(user_a):
    return {"Authorization": f"Bearer {_token(user_a)}"}


@pytest.fixture
def auth_a(user_a):
    return {"Authorization": f"Bearer {_token(user_a)}"}


@pytest.fixture
def auth_b(user_b):
    return {"Authorization": f"Bearer {_token(user_b)}"}


PITCH = (
    "BillWise is invoicing and GST-compliant billing software for Indian "
    "small businesses. We will charge SMBs 499 INR per month for unlimited "
    "invoices, targeting shop owners and freelancers who currently use "
    "Excel or Tally. GST filing is complex and error-prone for small teams, "
    "so we automate compliance and reconciliation. We plan to reach "
    "customers through WhatsApp referrals from chartered accountants, who "
    "currently onboard most small businesses onto accounting tools. Zoho "
    "Books, Vyapar and Tally already serve this market, but we believe our "
    "GST-first workflow and lower price will win switchers."
)
TARGET = {"geo": "IN", "segment": "smb"}


@pytest.fixture
async def project(client, auth):
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH,
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def run(client, auth, project):
    r = await client.post(f"/projects/{project}/runs", headers=auth)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]
