"""RLS write-path audit (batch M follow-up).

`sources` had RLS enabled with only a SELECT policy (0002_rls.sql) and no
policy granting INSERT at all -- so every real write to it, made as
`authenticated` (the role the orchestrator writes under, precisely so RLS
applies to service-side writes too), was silently denied. Every test that
exercised `SourceRepo`/`sources` up to this point ran as `postgres`, which
OWNS the table; `sources` was never given `FORCE ROW LEVEL SECURITY` (unlike
`evidence_items`), so the owner bypasses RLS entirely and the gap was
invisible to the suite. 0006_sources_insert_policy.sql closes it.

This file is the fix for the class of bug, not just the one table: every
table the pipeline actually writes to is probed here as `authenticated` with
a real JWT claim set, the same way `auth.uid()`/`auth.role()` resolve in
production (see `auth.uid()`'s own definition -- it reads
`request.jwt.claims->>'sub'`). A test run as the table owner proves nothing
about whether the production write path can write; only a test that
switches role does.

`assumption_classes` and `domain_tiers` are deliberately checked to STILL
deny insert -- they are hand-seeded, read-only reference data (P4), and a
write path opening up for them would itself be a regression.
"""
import json

import psycopg
import pytest


def _seed_chain(conn) -> dict:
    """One auth user + project + run + assumption + source + evidence +
    conflict, inserted as `postgres` (bypasses RLS) so every downstream
    per-table probe below has a real, user-owned FK chain to insert against."""
    cur = conn.cursor()

    cur.execute(
        "insert into auth.users (instance_id, id, aud, role, email, "
        "encrypted_password, created_at, updated_at) "
        "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
        "'authenticated', 'authenticated', "
        "'rls-' || gen_random_uuid() || '@test.local', '', now(), now()) "
        "returning id"
    )
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
        "values ('https://rls-seed.test/p', 'rls-seed.test', 1, 200) returning id"
    )
    source_id = cur.fetchone()[0]

    cur.execute(
        "insert into evidence_items (project_id, run_id, assumption_id, source_id, chair, "
        "direction, scope_geo, scope_segment, confidence, excerpt, dedup_hash) "
        "values (%s, %s, %s, %s, 'market', 'supports', 'IN', 'smb', 0.8, 'e', "
        "'rls-seed-hash') returning id",
        (project_id, run_id, assumption_id, source_id))
    evidence_id = cur.fetchone()[0]

    cur.execute(
        "insert into conflicts (project_id, run_id, assumption_id, kind, left_ref, "
        "rule, severity) values (%s, %s, %s, 'no_evidence', '{}', 'R1', 'low') "
        "returning id",
        (project_id, run_id, assumption_id))
    conflict_id = cur.fetchone()[0]

    return {
        "user_id": user_id, "project_id": project_id, "run_id": run_id,
        "assumption_id": assumption_id, "source_id": source_id,
        "evidence_id": evidence_id, "conflict_id": conflict_id,
    }


def _as_authenticated(conn, user_id) -> None:
    """Switches the rest of this transaction to the `authenticated` role
    with a real JWT claim set, the same as `auth.uid()`/`auth.role()` see in
    production. `set local` and `set_config(..., true)` both scope to the
    current transaction, so this reverts automatically when the `conn`
    fixture rolls back at teardown -- nothing here needs its own cleanup."""
    cur = conn.cursor()
    cur.execute("set local role authenticated")
    cur.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": str(user_id), "role": "authenticated"}),))


def _assert_insert_ok(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    assert row is not None and row[0] is not None


# ── the fixed gap ────────────────────────────────────────────────────────

def test_a_source_can_be_inserted_as_the_authenticated_role(conn):
    """The owner bypasses non-forced RLS, so a test running as postgres
    proves nothing about the production write path. Exercise the role the
    orchestrator actually uses. Regression test for the gap
    0006_sources_insert_policy.sql closes."""
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn,
        "insert into sources (canonical_url, domain, tier, http_status) "
        "values ('https://rls-probe.test/p','rls-probe.test',1,200) returning id")


# ── the full audit: every other table the pipeline writes ──────────────

def test_projects_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into projects (user_id, name, target_scope) "
             "values (%s, 'p2', '{}') returning id", (seed["user_id"],))


def test_runs_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into runs (project_id, user_id, kind, status, thread_id) "
             "values (%s,%s,'initial','pending','t2') returning id",
        (seed["project_id"], seed["user_id"]))


def test_pitches_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into pitches (project_id, body) values (%s, %s) returning id",
        (seed["project_id"], "x" * 200))


def test_assumptions_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into assumptions (project_id, run_id, statement, origin, "
             "criticality, uncertainty, falsifiability) values (%s,%s,'s2','founder',"
             "'blocking','unknown','testable_now') returning id",
        (seed["project_id"], seed["run_id"]))


def test_evidence_items_insertable_as_authenticated(conn):
    """Expected to already work -- Phase 0 gave evidence_items an explicit
    insert policy (0003_immutability.sql) -- verified here rather than
    assumed."""
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into evidence_items (project_id, run_id, assumption_id, "
             "source_id, chair, direction, scope_geo, scope_segment, confidence, "
             "excerpt, dedup_hash) values (%s,%s,%s,%s,'market','supports','IN',"
             "'smb',0.8,'e2','rls-probe-hash') returning id",
        (seed["project_id"], seed["run_id"], seed["assumption_id"], seed["source_id"]))


def test_conflicts_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into conflicts (project_id, run_id, assumption_id, kind, "
             "left_ref, rule, severity) values (%s,%s,%s,'no_evidence','{}','R1','low') "
             "returning id",
        (seed["project_id"], seed["run_id"], seed["assumption_id"]))


def test_position_deltas_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into position_deltas (conflict_id, chair, before, after, reason) "
             "values (%s,'market','a','b','r') returning id",
        (seed["conflict_id"],))


def test_model_runs_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into model_runs (project_id, run_id, template_key, parameters, "
             "outputs, breakpoints, sensitivity, viable) "
             "values (%s,%s,'k','{}','{}','{}','{}',true) returning id",
        (seed["project_id"], seed["run_id"]))


def test_experiments_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into experiments (project_id, assumption_id, method, "
             "instructions, kill_criterion, criterion_spec, priority) "
             "values (%s,%s,'fake_door','instr','kill','{}',1) returning id",
        (seed["project_id"], seed["assumption_id"]))


def test_verdicts_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into verdicts (run_id, project_id, decision, "
             "evidence_confidence, components, friction, rationale) "
             "values (%s,%s,'PIVOT',50,'{}','{}','r') returning id",
        (seed["run_id"], seed["project_id"]))


def test_ledger_versions_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into ledger_versions (project_id, run_id, version, snapshot, diff) "
             "values (%s,%s,99,'{}','{}') returning id",
        (seed["project_id"], seed["run_id"]))


def test_run_events_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into run_events (run_id, node, event) "
             "values (%s,'n','node_start') returning id",
        (seed["run_id"],))


def test_source_chunks_insertable_as_authenticated(conn):
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    _assert_insert_ok(
        conn, "insert into source_chunks (source_id, chunk_index, content) "
             "values (%s,0,'c') returning id",
        (seed["source_id"],))


# ── confirm the read-only reference tables correctly stay closed ───────

def test_assumption_classes_remains_read_only_for_authenticated(conn):
    """P4: the coverage denominator is hand-seeded, never written by the
    app. A write path opening up here would itself be a regression."""
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.cursor().execute(
            "insert into assumption_classes (key, archetype, label, question, "
            "crit_weight) values ('audit.probe','marketplace','l','q',1.0)")


def test_domain_tiers_remains_read_only_for_authenticated(conn):
    """PRD §16.2: the domain->tier map is hand-seeded reference data."""
    seed = _seed_chain(conn)
    _as_authenticated(conn, seed["user_id"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.cursor().execute(
            "insert into domain_tiers (domain, tier) values ('audit-probe.test', 1)")
