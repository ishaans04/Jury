"""0007_evidence_delete_via_cascade.sql -- the fix for the batch-N audit
finding: 0003_immutability.sql revoked DELETE on `evidence_items` from every
role including the table owner, which (because a referential CASCADE action
runs as the owner, not as the deleting role) silently made it impossible to
ever delete a project or an auth user -- both of which the schema's own
`on delete cascade` FKs presume are deletable.

Five properties prove the fix is exactly as narrow as intended:
  1. `authenticated` still cannot issue a bare DELETE on evidence_items.
  2. Deleting a project succeeds and cascades away its evidence.
  3. Deleting the owning auth user succeeds and cascades all the way through.
  4. UPDATE on evidence is still blocked -- for `authenticated` and for a
     genuine superuser (proves the REVOKE was untouched and the trigger,
     which this migration deliberately leaves alone, still holds).
  5. TRUNCATE is still blocked -- for `authenticated` and for a superuser.

Uses the same `conn` (postgres, owner, not a real superuser here) and
`admin_conn` (supabase_admin, a genuine superuser) pattern as
tests/test_db_constraints.py, and the same `_as_authenticated` role-switch as
tests/test_rls_write_paths.py.
"""
import json
import os
from dataclasses import dataclass

import psycopg
import pytest

ADMIN_DATABASE_URL = os.environ.get(
    "SUPABASE_ADMIN_DATABASE_URL",
    "postgresql://supabase_admin:postgres@127.0.0.1:54322/postgres",
)


@pytest.fixture
def admin_conn():
    connection = psycopg.connect(ADMIN_DATABASE_URL)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@dataclass(frozen=True)
class Seeded:
    user_id: str
    project_id: str
    run_id: str
    assumption_id: str
    source_id: str
    evidence_id: str


def _seed_minimal(conn) -> Seeded:
    cur = conn.cursor()
    cur.execute(
        "insert into auth.users (instance_id, id, aud, role, email, "
        "encrypted_password, created_at, updated_at) "
        "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
        "'authenticated', 'authenticated', "
        "'del-' || gen_random_uuid() || '@test.local', '', now(), now()) "
        "returning id")
    user_id = cur.fetchone()[0]

    cur.execute(
        "insert into projects (user_id, name, target_scope) values (%s, 'p', '{}') "
        "returning id", (user_id,))
    project_id = cur.fetchone()[0]

    cur.execute(
        "insert into runs (project_id, user_id, kind, status, thread_id) "
        "values (%s, %s, 'initial', 'pending', 't1') returning id",
        (project_id, user_id))
    run_id = cur.fetchone()[0]

    cur.execute(
        "insert into assumptions (project_id, run_id, statement, origin, criticality, "
        "uncertainty, falsifiability) values (%s, %s, 's', 'founder', 'blocking', "
        "'unknown', 'testable_now') returning id",
        (project_id, run_id))
    assumption_id = cur.fetchone()[0]

    cur.execute(
        "insert into sources (canonical_url, domain, tier, http_status) "
        "values ('https://del-cascade.test/p', 'del-cascade.test', 1, 200) "
        "returning id")
    source_id = cur.fetchone()[0]

    cur.execute(
        "insert into evidence_items (project_id, run_id, assumption_id, source_id, chair, "
        "direction, scope_geo, scope_segment, confidence, excerpt, dedup_hash) "
        "values (%s, %s, %s, %s, 'market', 'supports', 'IN', 'smb', 0.8, 'e', "
        "'del-cascade-hash-' || %s) returning id",
        (project_id, run_id, assumption_id, source_id, str(project_id)))
    evidence_id = cur.fetchone()[0]

    return Seeded(user_id=user_id, project_id=project_id, run_id=run_id,
                 assumption_id=assumption_id, source_id=source_id,
                 evidence_id=evidence_id)


def _as_authenticated(conn, user_id) -> None:
    """See tests/test_rls_write_paths.py: switches the rest of this
    transaction to `authenticated` with a real JWT claim, exactly as
    production RLS sees it. Scoped to the transaction, so the `conn`
    fixture's rollback at teardown reverts it -- no cleanup needed here."""
    cur = conn.cursor()
    cur.execute("set local role authenticated")
    cur.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": str(user_id), "role": "authenticated"}),))


def _count_evidence_for_project(conn, project_id) -> int:
    """Runs as whatever role currently holds the connection. `reset role`
    first when the caller needs the owner's unrestricted view (RLS-scoped
    counts as `authenticated` would otherwise read as zero for the wrong
    reason once the owning project row is gone)."""
    cur = conn.cursor()
    cur.execute("reset role")
    cur.execute("select count(*) from evidence_items where project_id = %s",
               (project_id,))
    return cur.fetchone()[0]


# ── property 1: authenticated still cannot bare-DELETE evidence ──────────

def test_authenticated_cannot_delete_evidence_directly(conn):
    seeded = _seed_minimal(conn)
    _as_authenticated(conn, seeded.user_id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("delete from evidence_items where id = %s",
                       (seeded.evidence_id,))


# ── property 2: deleting a project cascades its evidence ─────────────────

def test_deleting_a_project_cascades_its_evidence(conn):
    """The exact path this migration exists for: a user erasing their own
    project must actually remove the evidence rows filed under it, not hit
    `permission denied for table evidence_items` on the CASCADE."""
    seeded = _seed_minimal(conn)
    _as_authenticated(conn, seeded.user_id)
    with conn.cursor() as cur:
        cur.execute("delete from projects where id = %s", (seeded.project_id,))
    assert _count_evidence_for_project(conn, seeded.project_id) == 0


# ── property 3: deleting the auth user cascades all the way through ──────

def test_deleting_the_auth_user_cascades_through_to_evidence(conn):
    """Account deletion: auth.users -> projects -> evidence_items, two
    cascades deep. Connects as `postgres` directly (auth.users is managed by
    Supabase Auth, not reachable as `authenticated` at all)."""
    seeded = _seed_minimal(conn)
    with conn.cursor() as cur:
        cur.execute("delete from auth.users where id = %s", (seeded.user_id,))
    assert _count_evidence_for_project(conn, seeded.project_id) == 0


# ── property 4: UPDATE stays blocked, both as owner and as a superuser ───

def test_authenticated_still_cannot_update_evidence(conn):
    seeded = _seed_minimal(conn)
    _as_authenticated(conn, seeded.user_id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("update evidence_items set confidence = 0.1 where id = %s",
                       (seeded.evidence_id,))


def test_a_superuser_still_cannot_update_evidence(admin_conn):
    """Unaffected by this migration: the UPDATE trigger is untouched, so this
    still holds even against a role that bypasses every GRANT/REVOKE."""
    seeded = _seed_minimal(admin_conn)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        with admin_conn.cursor() as cur:
            cur.execute("update evidence_items set confidence = 0.1 where id = %s",
                       (seeded.evidence_id,))


# ── property 5: TRUNCATE stays blocked, both as authenticated and superuser ──

def test_authenticated_still_cannot_truncate_evidence(conn):
    _seed_minimal(conn)
    _as_authenticated(conn, None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("truncate evidence_items cascade")


def test_a_superuser_still_cannot_truncate_evidence(admin_conn):
    """Unaffected by this migration: the statement-level TRUNCATE trigger
    from 0005_evidence_no_truncate.sql is untouched."""
    _seed_minimal(admin_conn)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        with admin_conn.cursor() as cur:
            cur.execute("truncate evidence_items cascade")
