import os
from dataclasses import dataclass

import psycopg
import pytest

# supabase_admin is the one role in this stack that is a genuine Postgres
# superuser (rolsuper=true, verified against pg_roles on the running local
# database). `postgres` -- the role conftest.py's `conn` fixture and every
# other test in this file connect as, and the owner of evidence_items -- is
# NOT a superuser here (rolsuper=false; it only carries rolbypassrls). That
# matters for P6: REVOKE actually stops `postgres` (ordinary ACL check), so
# only a connection as a real superuser can prove the trigger, not the
# REVOKE, is what makes evidence_items unconditionally immutable.
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


def test_position_deltas_chair_is_constrained_to_the_five_chairs(conn):
    """Chairs are a closed set; an unconstrained value would render as a
    broken conceding-chair label in the conflict UI."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into position_deltas (conflict_id, chair, before, after, reason) "
                "values (gen_random_uuid(), 'Visionary', 'a', 'b', 'r')")


@dataclass(frozen=True)
class SeededFixtures:
    """The FK chain an evidence row needs, seeded fresh per test.

    A dataclass rather than a bare tuple: different tests need different
    subsets of these fields, and positional unpacking of six similarly-typed
    uuids is exactly the kind of thing that silently picks up the wrong field
    after an edit.
    """

    user_id: str
    project_id: str
    run_id: str
    assumption_id: str
    source_id: str
    evidence_id: str


def _seed_minimal(conn) -> SeededFixtures:
    """Create one user, project, run, assumption, source, and evidence row.

    Uses a single cursor with explicit sequencing (insert, fetch its id, use
    that id in the next insert) so there is never any ambiguity about which
    statement's result is being read.

    auth.users is managed by Supabase Auth, not by this schema. Queried against
    the running local database (information_schema.columns, table_schema='auth',
    table_name='users', is_nullable='NO'), its only NOT NULL columns are `id`
    (no default -- must be supplied) and `is_sso_user` / `is_anonymous` (both
    default to false, so they need not be supplied at all). A bare `(id)` insert
    would therefore satisfy every NOT NULL constraint, but the fuller column
    list below is kept because it is what GoTrue itself writes and is more
    representative of a real row; the unique-per-call email avoids collisions
    across repeated runs.
    """
    cur = conn.cursor()

    cur.execute(
        "insert into auth.users (instance_id, id, aud, role, email, "
        "encrypted_password, created_at, updated_at) "
        "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
        "'authenticated', 'authenticated', "
        "'p0-' || gen_random_uuid() || '@test.local', '', now(), now()) "
        "returning id"
    )
    user_id = cur.fetchone()[0]

    cur.execute(
        "insert into projects (user_id, name, target_scope) values (%s, 'p', '{}') "
        "returning id",
        (user_id,),
    )
    project_id = cur.fetchone()[0]

    cur.execute(
        "insert into runs (project_id, user_id, kind, status, thread_id) "
        "values (%s, %s, 'initial', 'pending', 't1') returning id",
        (project_id, user_id),
    )
    run_id = cur.fetchone()[0]

    cur.execute(
        "insert into assumptions (project_id, run_id, statement, origin, criticality, "
        "uncertainty, falsifiability) values (%s, %s, 's', 'founder', 'blocking', "
        "'unknown', 'testable_now') returning id",
        (project_id, run_id),
    )
    assumption_id = cur.fetchone()[0]

    cur.execute(
        "insert into sources (canonical_url, domain, tier, http_status) "
        "values ('https://x.test/p', 'x.test', 1, 200) returning id"
    )
    source_id = cur.fetchone()[0]

    cur.execute(
        "insert into evidence_items (project_id, run_id, assumption_id, source_id, chair, "
        "direction, scope_geo, scope_segment, confidence, excerpt, dedup_hash) "
        "values (%s, %s, %s, %s, 'market', 'supports', 'IN', 'smb', 0.8, 'e', 'h1') "
        "returning id",
        (project_id, run_id, assumption_id, source_id),
    )
    evidence_id = cur.fetchone()[0]

    return SeededFixtures(
        user_id=user_id,
        project_id=project_id,
        run_id=run_id,
        assumption_id=assumption_id,
        source_id=source_id,
        evidence_id=evidence_id,
    )


def test_evidence_immutable_at_database_level(conn):
    """P6: corrections supersede, never update.

    Connected as `postgres` -- the role the app and every other test in this
    file use to reach the database, and the owner of evidence_items. Until
    0009_evidence_items_fk_lock_privilege.sql (Task 5.2, batch-S audit), the
    REVOKE in 0003_immutability.sql stopped this UPDATE for `postgres`
    directly, before the trigger was ever reached (InsufficientPrivilege).
    0009 restores UPDATE to `postgres` (and anon/authenticated/service_role)
    because Postgres's own FK-existence check -- `SELECT ... FOR KEY SHARE`,
    run whenever another table inserts a row referencing evidence_items,
    e.g. position_deltas.new_evidence_id -- requires UPDATE privilege on the
    table being locked, which the blanket REVOKE made structurally
    impossible for literally every role to satisfy. See 0009's own
    migration comment for the full mechanism and how it was reproduced.
    That grant does not reopen P6: the BEFORE UPDATE trigger raises
    unconditionally regardless of grants, for every role -- this test now
    proves exactly that for `postgres` (RaiseException, not
    InsufficientPrivilege), the same guarantee
    test_evidence_immutable_against_superuser_at_database_level below
    already proved for a role the REVOKE could never have touched in the
    first place.
    """
    seeded = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        with conn.cursor() as cur:
            cur.execute(
                "update evidence_items set confidence = 0.1 where id = %s",
                (seeded.evidence_id,),
            )


def test_evidence_not_directly_deletable_by_any_application_role(conn):
    """P6 narrowed (0007_evidence_delete_via_cascade.sql,
    0008_evidence_fk_cascades.sql -- batch-N audit): corrections still
    supersede, never update -- and no application role may issue a bare
    DELETE either. This used to assert DELETE raised InsufficientPrivilege
    for `postgres` too, but that REVOKE had a blast radius past its intent:
    a referential CASCADE action runs as the table owner, so revoking DELETE
    from the owner made it impossible to ever delete a project or an auth
    user, both of which evidence_items.project_id/assumption_id already
    declare ON DELETE CASCADE for. Erasure of an entire project is different
    in kind from an in-place correction -- nothing is falsified, the record
    is withdrawn at the owner's request -- and is reachable only via
    cascade, never directly by any of the roles the application actually
    connects as. See test_evidence_deletable_only_as_a_cascade below and
    tests/test_evidence_delete_via_cascade.py's erasure tests."""
    with conn.cursor() as cur:
        for role in ("anon", "authenticated", "service_role"):
            cur.execute(
                "select has_table_privilege(%s, 'evidence_items', 'DELETE')",
                (role,))
            assert cur.fetchone()[0] is False, f"{role} must not hold DELETE"


def test_evidence_deletable_only_as_a_cascade(conn):
    """The table owner retains DELETE solely so referential actions can run:
    a NO ACTION foreign key referencing evidence_items would force a KEY
    SHARE lock needing UPDATE privilege, which P6 permanently denies --
    without DELETE restored to the owner, a project or account deletion
    could never cascade through to the evidence it owns (this is exactly
    the failure 0007/0008 fix). Postgres has no notion of "DELETE only via
    cascade": the same owner grant that makes the cascade possible also
    permits this direct, targeted delete by that role -- demonstrated here
    rather than hidden, precisely because no other role
    (test_evidence_not_directly_deletable_by_any_application_role, above)
    can reach it."""
    seeded = _seed_minimal(conn)
    with conn.cursor() as cur:
        cur.execute("delete from evidence_items where id = %s", (seeded.evidence_id,))
        cur.execute("select count(*) from evidence_items where id = %s",
                   (seeded.evidence_id,))
        assert cur.fetchone()[0] == 0


def test_evidence_immutable_against_superuser_at_database_level(admin_conn):
    """P6 must hold even against a genuine Postgres superuser (supabase_admin;
    rolsuper=true), which bypasses the REVOKE entirely -- superusers skip
    ordinary privilege checks. Only the BEFORE UPDATE trigger can stop this
    connection, which is what proves the trigger -- not the REVOKE -- is the
    part of 0003_immutability.sql that makes P6 hold unconditionally."""
    seeded = _seed_minimal(admin_conn)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        with admin_conn.cursor() as cur:
            cur.execute(
                "update evidence_items set confidence = 0.1 where id = %s",
                (seeded.evidence_id,),
            )


def test_evidence_deletable_by_a_superuser_too(admin_conn):
    """P6 narrowed (0007/0008, batch-N audit): a genuine superuser
    (supabase_admin) already bypassed the REVOKE entirely, so only the
    BEFORE DELETE row trigger ever stopped it here -- and that trigger is
    exactly what 0007_evidence_delete_via_cascade.sql dropped, because it
    blocked the CASCADE this fix exists to unblock. UPDATE (the test above)
    is untouched and still raises unconditionally, superuser included."""
    seeded = _seed_minimal(admin_conn)
    with admin_conn.cursor() as cur:
        cur.execute("delete from evidence_items where id = %s", (seeded.evidence_id,))
        cur.execute("select count(*) from evidence_items where id = %s",
                   (seeded.evidence_id,))
        assert cur.fetchone()[0] == 0


def test_evidence_untruncatable_by_revoked_roles(conn):
    """P6, TRUNCATE side, REVOKE-covered roles.

    TRUNCATE is a distinct grantable privilege and a distinct trigger event
    from UPDATE/DELETE in Postgres -- it bypasses RLS entirely (FORCE ROW
    LEVEL SECURITY does not apply to it) and fires no row-level trigger. This
    was the fix-round-1 hole: 0003_immutability.sql revoked only update/delete
    and installed only row-level triggers, leaving TRUNCATE (which would
    cascade into position_deltas via new_evidence_id) wide open, including to
    service_role -- the exact role P6 names. Connects as `postgres` (this
    file's default connection) and switches to `service_role` for the
    statement under test, mirroring how the reviewer reproduced the exploit.
    """
    _seed_minimal(conn)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("set local role service_role")
            cur.execute("truncate evidence_items cascade")


def test_evidence_untruncatable_by_superuser(admin_conn):
    """P6, TRUNCATE side, against a genuine superuser. The REVOKE in
    0005_evidence_no_truncate.sql cannot stop supabase_admin (superusers skip
    ordinary privilege checks); only the FOR EACH STATEMENT trigger can, and
    does."""
    _seed_minimal(admin_conn)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        with admin_conn.cursor() as cur:
            cur.execute("truncate evidence_items cascade")


def test_dedup_hash_unique_per_project(conn):
    """P10: the same source twice must never inflate confidence."""
    seeded = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into evidence_items (project_id, run_id, assumption_id, source_id, "
                "chair, direction, scope_geo, scope_segment, confidence, excerpt, dedup_hash) "
                "values (%s, %s, %s, %s, 'customer', 'supports', 'IN', 'smb', 0.9, 'e2', 'h1')",
                (seeded.project_id, seeded.run_id, seeded.assumption_id, seeded.source_id),
            )


def test_tier_five_source_rejected(conn):
    """P1: tier 5 is a model prior, not evidence. It must be impossible to persist."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values ('https://y.test/p', 'y.test', 5, 200)"
            )


def test_non_2xx_source_rejected(conn):
    """P1: no fetched 2xx response, no source row."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values ('https://z.test/p', 'z.test', 1, 403)"
            )


def test_discovered_assumption_must_name_a_chair(conn):
    """A `discovered` assumption without a discovering chair is meaningless --
    the UI has nowhere to attribute it."""
    seeded = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into assumptions (project_id, run_id, statement, origin, "
                "criticality, uncertainty, falsifiability) values "
                "(%s, %s, 's', 'discovered', 'high', 'unknown', 'testable_now')",
                (seeded.project_id, seeded.run_id),
            )


def test_founder_assumption_must_not_name_a_chair(conn):
    """The other direction of the same constraint: a founder-origin assumption
    was never discovered by a chair, so attributing one is a modelling error,
    not a legitimate provenance."""
    seeded = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into assumptions (project_id, run_id, statement, origin, "
                "discovered_by, criticality, uncertainty, falsifiability) values "
                "(%s, %s, 's', 'founder', 'market', 'high', 'unknown', 'testable_now')",
                (seeded.project_id, seeded.run_id),
            )


def test_rls_is_enabled_on_every_table(conn):
    """Structural check: RLS must be turned on for every table in the schema,
    not just the ones that happen to have a policy. A table with policies but
    RLS disabled would still be wide open."""
    tables = [
        "profiles", "projects", "runs", "pitches", "assumptions", "evidence_items",
        "source_chunks", "conflicts", "position_deltas", "model_runs", "experiments",
        "verdicts", "ledger_versions", "run_events", "sources", "assumption_classes",
        "domain_tiers",
    ]
    with conn.cursor() as cur:
        cur.execute(
            "select relname, relrowsecurity, relforcerowsecurity from pg_class "
            "where relname = any(%s) and relnamespace = 'public'::regnamespace",
            (tables,),
        )
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    assert set(rows) == set(tables), f"missing tables: {set(tables) - set(rows)}"
    not_enabled = [t for t, (enabled, _) in rows.items() if not enabled]
    assert not not_enabled, f"RLS not enabled on: {not_enabled}"
    # evidence_items additionally forces RLS so it applies to the table owner too.
    assert rows["evidence_items"][1] is True


def test_rls_policies_exist_for_project_scoped_tables(conn):
    """Structural check: every project-scoped table has at least one policy,
    evidence_items has exactly insert+select (no update/delete policy exists
    at all), and the two public-reference tables have their read-only policy.

    This proves the policies are wired up: present, attached to the right
    tables, and for evidence_items, restricted to the two commands that
    should be reachable at all. The tests below prove the policies actually
    *behave* correctly under auth.uid() by authenticating as a real
    non-superuser role with a JWT claim, the same mechanism PostgREST uses.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select tablename, cmd from pg_policies where schemaname = 'public' "
            "order by tablename, cmd"
        )
        rows = cur.fetchall()
    by_table = {}
    for tablename, cmd in rows:
        by_table.setdefault(tablename, set()).add(cmd)

    project_scoped = [
        "profiles", "projects", "runs", "pitches", "assumptions", "conflicts",
        "model_runs", "experiments", "verdicts", "ledger_versions",
        "position_deltas", "run_events", "source_chunks",
    ]
    for t in project_scoped:
        assert t in by_table and by_table[t], f"no policy on {t}"

    assert by_table["evidence_items"] == {"INSERT", "SELECT"}, (
        f"evidence_items must have exactly insert+select policies, got "
        f"{by_table.get('evidence_items')}"
    )
    assert "SELECT" in by_table["sources"]
    assert "UPDATE" not in by_table.get("sources", set())
    assert "SELECT" in by_table["assumption_classes"]
    assert "SELECT" in by_table["domain_tiers"]


def _insert_user(cur) -> str:
    """A second, lighter-weight auth.users insert for the RLS behavioural
    tests below, which need several distinct users rather than a full
    evidence FK chain per user."""
    cur.execute(
        "insert into auth.users (instance_id, id, aud, role, email, "
        "encrypted_password, created_at, updated_at) values "
        "('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
        "'authenticated', 'authenticated', 'u-' || gen_random_uuid() || "
        "'@test.local', '', now(), now()) returning id"
    )
    return cur.fetchone()[0]


def _authenticate_as(cur, user_id) -> None:
    """Switch the rest of this transaction to the `authenticated` role with a
    JWT claim naming `user_id` as auth.uid() -- the same mechanism PostgREST
    uses for a real request. Both `set local role` and `set_config(..., true)`
    are transaction-scoped, so this reverts automatically when the test's
    connection is rolled back by the `conn` fixture."""
    cur.execute("set local role authenticated")
    cur.execute(
        "select set_config('request.jwt.claims', %s, true)",
        ('{"sub":"%s","role":"authenticated"}' % user_id,),
    )


def test_rls_projects_scoped_to_owner(conn):
    """Behavioural check that auth.uid() = user_id actually gates `projects`,
    not just that a policy exists for it. Two projects are seeded (as
    `postgres`, which bypasses RLS via rolbypassrls, exactly like the
    dashboard/migrations connection), then the same transaction authenticates
    as one owner and must see only that owner's project -- and must be unable
    to insert a project claiming to belong to the other owner."""
    with conn.cursor() as cur:
        u1 = _insert_user(cur)
        u2 = _insert_user(cur)
        cur.execute(
            "insert into projects (user_id, name, target_scope) values (%s,'p1','{}') "
            "returning id",
            (u1,),
        )
        p1 = cur.fetchone()[0]
        cur.execute(
            "insert into projects (user_id, name, target_scope) values (%s,'p2','{}') "
            "returning id",
            (u2,),
        )
        cur.fetchone()

        _authenticate_as(cur, u1)
        cur.execute("select id from projects")
        assert {r[0] for r in cur.fetchall()} == {p1}

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "insert into projects (user_id, name, target_scope) values (%s,'bad','{}')",
                (u2,),
            )


def test_rls_child_table_scoped_through_project(conn):
    """Behavioural check for the child-table pattern (authorise through
    project_id), exercised on `runs` -- representative of the eight tables
    the shared do-block policy in 0002_rls.sql covers."""
    with conn.cursor() as cur:
        u1 = _insert_user(cur)
        u2 = _insert_user(cur)
        cur.execute(
            "insert into projects (user_id, name, target_scope) values (%s,'p1','{}') "
            "returning id",
            (u1,),
        )
        p1 = cur.fetchone()[0]
        cur.execute(
            "insert into projects (user_id, name, target_scope) values (%s,'p2','{}') "
            "returning id",
            (u2,),
        )
        p2 = cur.fetchone()[0]
        cur.execute(
            "insert into runs (project_id, user_id, kind, status, thread_id) "
            "values (%s,%s,'initial','pending','t1') returning id",
            (p1, u1),
        )
        r1 = cur.fetchone()[0]
        cur.execute(
            "insert into runs (project_id, user_id, kind, status, thread_id) "
            "values (%s,%s,'initial','pending','t2') returning id",
            (p2, u2),
        )
        cur.fetchone()

        _authenticate_as(cur, u1)
        cur.execute("select id from runs")
        assert {r[0] for r in cur.fetchall()} == {r1}


def test_rls_grandchild_table_scoped_through_parent(conn):
    """Behavioural check for the grandchild pattern (authorise through the
    parent's project_id), exercised on `run_events`, which authorises through
    `runs`."""
    with conn.cursor() as cur:
        u1 = _insert_user(cur)
        u2 = _insert_user(cur)
        cur.execute(
            "insert into projects (user_id, name, target_scope) values (%s,'p1','{}') "
            "returning id",
            (u1,),
        )
        p1 = cur.fetchone()[0]
        cur.execute(
            "insert into projects (user_id, name, target_scope) values (%s,'p2','{}') "
            "returning id",
            (u2,),
        )
        p2 = cur.fetchone()[0]
        cur.execute(
            "insert into runs (project_id, user_id, kind, status, thread_id) "
            "values (%s,%s,'initial','pending','t1') returning id",
            (p1, u1),
        )
        r1 = cur.fetchone()[0]
        cur.execute(
            "insert into runs (project_id, user_id, kind, status, thread_id) "
            "values (%s,%s,'initial','pending','t2') returning id",
            (p2, u2),
        )
        r2 = cur.fetchone()[0]
        cur.execute(
            "insert into run_events (run_id, node, event) values (%s,'n1','node_start') "
            "returning id",
            (r1,),
        )
        e1 = cur.fetchone()[0]
        cur.execute(
            "insert into run_events (run_id, node, event) values (%s,'n2','node_start') "
            "returning id",
            (r2,),
        )
        cur.fetchone()

        _authenticate_as(cur, u1)
        cur.execute("select id from run_events")
        assert {r[0] for r in cur.fetchall()} == {e1}


def test_rls_sources_readable_by_any_authenticated_user(conn):
    """PRD §14.4: sources are deliberately global and shared -- any
    authenticated user must see a source regardless of who first fetched it,
    since a fetched pricing page is not private data and the whole point is a
    shared cache that reduces search-quota burn."""
    with conn.cursor() as cur:
        unrelated_user = _insert_user(cur)
        cur.execute(
            "insert into sources (canonical_url, domain, tier, http_status) "
            "values ('https://shared.test/p', 'shared.test', 1, 200) returning id"
        )
        source_id = cur.fetchone()[0]

        _authenticate_as(cur, unrelated_user)
        cur.execute("select id from sources where id = %s", (source_id,))
        assert cur.fetchone() == (source_id,)
