"""jury.api.main / deps / routers.*. Task 4.4.

Uses the real local Postgres (see tests/api/conftest.py) the same way every
other DB-backed package in this repo does; `client` is an httpx.AsyncClient
wired directly to the ASGI app (no real socket).
"""
import time

import pytest
from jose import jwt

from jury.schemas.enums import Archetype
from tests.api.conftest import PITCH, TARGET, TEST_JWT_SECRET

ARCHETYPES = set(Archetype)


# ── auth ──────────────────────────────────────────────────────────────────

async def test_health_needs_no_auth(client):
    r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.parametrize("method,path", [
    ("POST", "/projects"), ("GET", "/projects"), ("GET", "/runs/abc"),
    ("POST", "/runs/abc/hearing/confirm"), ("GET", "/runs/abc/events"),
])
async def test_every_other_route_rejects_a_missing_token(client, method, path):
    r = await client.request(method, path, json={})
    assert r.status_code == 401


async def test_a_forged_token_is_rejected(client):
    r = await client.get("/projects", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_a_token_signed_with_the_wrong_secret_is_rejected(client, user_a):
    bad = jwt.encode({"sub": user_a, "aud": "authenticated", "role": "authenticated",
                      "exp": int(time.time()) + 3600}, "wrong-secret", algorithm="HS256")
    r = await client.get("/projects", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


async def test_an_expired_token_is_rejected(client, user_a):
    expired = jwt.encode(
        {"sub": user_a, "aud": "authenticated", "role": "authenticated",
         "exp": int(time.time()) - 10}, TEST_JWT_SECRET, algorithm="HS256")
    r = await client.get("/projects", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


# ── project intake ────────────────────────────────────────────────────────

async def test_create_project_returns_archetype_and_confidence(client, auth):
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH,
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["archetype"] in {a.value for a in ARCHETYPES}
    assert 0 <= body["archetype_confidence"] <= 1


async def test_a_pitch_under_200_chars_is_rejected(client, auth):
    r = await client.post("/projects", json={"name": "X", "pitch": "too short",
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 422


async def test_a_pitch_over_2000_chars_is_rejected(client, auth):
    r = await client.post("/projects", json={"name": "X", "pitch": "x" * 2001,
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 422


async def test_target_scope_is_required_at_intake(client, auth):
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH}, headers=auth)
    assert r.status_code == 422


async def test_archetype_can_be_overridden(client, auth, project):
    r = await client.patch(f"/projects/{project}", json={"archetype": "d2c"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["archetype"] == "d2c"


async def test_an_invalid_archetype_is_rejected(client, auth, project):
    r = await client.patch(f"/projects/{project}", json={"archetype": "unicorn"}, headers=auth)
    assert r.status_code == 422


# ── ownership ─────────────────────────────────────────────────────────────

async def test_one_user_cannot_read_another_users_project(client, auth_a, auth_b):
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH,
                                             "target_scope": TARGET}, headers=auth_a)
    created = r.json()
    r2 = await client.get(f"/projects/{created['id']}", headers=auth_b)
    assert r2.status_code in (403, 404)


async def test_one_user_cannot_start_a_run_on_another_users_project(client, auth_a, auth_b):
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH,
                                             "target_scope": TARGET}, headers=auth_a)
    created = r.json()
    r2 = await client.post(f"/projects/{created['id']}/runs", headers=auth_b)
    assert r2.status_code in (403, 404)


# ── run control ───────────────────────────────────────────────────────────

async def test_run_events_returns_the_trace(client, auth, run):
    r = await client.get(f"/runs/{run}/events", headers=auth)
    assert r.status_code == 200
    assert all({"node", "event", "ts"} <= set(e) for e in r.json())


async def test_hearing_confirm_resumes_the_run(client, auth, run):
    edited = [{"statement": "SMB owners will pay for GST automation.",
              "origin": "founder", "criticality": "blocking",
              "uncertainty": "uncertain", "falsifiability": "testable_now"}]
    r = await client.post(f"/runs/{run}/hearing/confirm",
                          json={"assumptions": edited}, headers=auth)
    assert r.status_code == 202


async def test_hearing_confirm_rejects_an_assumption_missing_an_axis(client, auth, run):
    bad = [{"statement": "A thing is true.", "origin": "founder"}]
    r = await client.post(f"/runs/{run}/hearing/confirm",
                          json={"assumptions": bad}, headers=auth)
    assert r.status_code == 422


async def test_cancel_retains_the_checkpoint(client, auth, run):
    r0 = await client.post(f"/runs/{run}/cancel", headers=auth)
    assert r0.status_code == 200
    r = await client.get(f"/runs/{run}", headers=auth)
    assert r.json()["thread_id"]


async def test_cancel_records_an_interrupt_trace_row(client, auth, run):
    """A cancelled-and-left run must be distinguishable from a normal one in
    the F17 trace, without touching the resumable checkpoint."""
    await client.post(f"/runs/{run}/cancel", headers=auth)
    events = (await client.get(f"/runs/{run}/events", headers=auth)).json()
    assert any(e["event"] == "interrupt" and e["node"] == "cancel"
               for e in events)


def _all_paths(routes) -> set[str]:
    paths: set[str] = set()
    for r in routes:
        if hasattr(r, "path"):
            paths.add(r.path)
        if hasattr(r, "routes"):
            paths |= _all_paths(r.routes)
    return paths


async def test_there_is_no_evidence_read_route(app):
    paths = _all_paths(app.routes)
    assert not any(p.endswith("/evidence") for p in paths)


# ── artifact upload ───────────────────────────────────────────────────────

async def test_an_oversized_artifact_upload_is_rejected(client, auth, project):
    r = await client.post(
        f"/projects/{project}/artifacts",
        files={"file": ("big.pdf", b"x" * (11 * 1024 * 1024), "application/pdf")},
        headers=auth)
    assert r.status_code == 413


async def test_an_unsupported_artifact_mime_type_is_rejected(client, auth, project):
    r = await client.post(
        f"/projects/{project}/artifacts",
        files={"file": ("x.exe", b"MZ", "application/x-msdownload")}, headers=auth)
    assert r.status_code == 415
