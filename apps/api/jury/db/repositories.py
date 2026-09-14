"""The only module that writes SQL (spec §6).

Every other module reaches Postgres through one of the repositories here --
never through a raw connection of its own. That single choke point is what
makes P6 enforceable in Python as well as in the schema: `EvidenceRepo`
simply has no method whose name suggests mutation, so there is no call a
caller could make, correct or mistaken, that would try to update or delete
an evidence row. The database already denies UPDATE/DELETE/TRUNCATE to every
role (0003_immutability.sql, 0005_evidence_no_truncate.sql) and would reject
such an attempt at runtime with a raised trigger exception -- but "the
database will reject it" is a worse guarantee than "the method does not
exist," because the former still requires something to attempt the mutation
and mishandle the resulting error. `test_evidence_repo_exposes_no_mutation_methods`
asserts the absence directly, by introspecting the class.

Exception policy (a decision this module had to make; not specified in the
brief): repository methods do NOT blanket-catch exceptions the way
`retrieval/fetch.py` and `retrieval/verify.py` do. Those two catch broadly
because a single flaky provider or a single bad source must degrade one
claim to a rejection, never crash the whole run -- degrading to less
evidence is *correct* behaviour for a transport that is expected to be
unreliable. A database outage is a different kind of failure: it is not
"one provider had a hiccup," it is "the run's entire persistence layer is
unavailable," and silently returning None/[] for that would look
indistinguishable from an ordinary empty result or an ordinary dedup skip,
hiding a systemic problem behind data that looks merely uneventful. So the
only exception any repository method catches is the one the brief names
explicitly: `insert_verified` catches `psycopg.errors.UniqueViolation`,
because a duplicate `dedup_hash` is an expected, documented business
outcome (P10 -- two chairs finding the same source is normal), not an
infrastructure failure. Every other exception (a lost connection, a bad
constraint, a pool timeout) propagates to the caller uncaught, the same way
`jury/llm/gateway.py` lets a fully-exhausted retry chain raise rather than
inventing an answer -- the orchestration layer above (Phase 4's chair loop)
is where a policy for "the database is down mid-run" belongs, not a
best-effort guess made silently in the data layer.

`insert_verified` computes `dedup_hash` itself, from
`(verified.canonical_url, verified.claim.variable, verified.claim.scope)`
via `jury.engines.dedup.dedup_hash` -- there is no parameter a caller could
use to supply one instead. A caller-supplied hash that disagreed with the
row's own url/variable/scope would silently defeat P10 (a wrong hash could
collide with an unrelated row, or fail to collide with a genuine duplicate);
computing it from the verified claim's own fields inside the repository is
what makes that impossible rather than merely policy.
"""
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from jury.engines.dedup import dedup_hash
from jury.retrieval.verify import VerifiedClaim


def _row_id(row) -> str:
    return str(row[0])


class SourceRepo:
    """`sources` is shared, globally-deduplicated reference data (PRD §14.4:
    "a fetched pricing page is not private data") written by every
    authenticated caller, not just the row's original inserter -- which is
    exactly why it must NOT have an UPDATE policy (0006_sources_insert_policy.sql):
    on a table nobody individually owns, an UPDATE grant would let any
    authenticated user silently rewrite another user's cached source
    metadata. `upsert` is therefore idempotent via `ON CONFLICT DO NOTHING`
    plus a follow-up read, never `DO UPDATE` -- the first insert's metadata
    wins and sticks; every later call for the same `canonical_url` is a
    pure no-op that just returns the existing row's id.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def upsert(self, canonical_url: str, domain: str, tier: int,
                     title: str | None, http_status: int,
                     storage_path: str | None = None) -> str:
        """Idempotent on `canonical_url` (the table's own unique constraint)
        without ever issuing an UPDATE: `ON CONFLICT DO NOTHING` means a
        colliding insert returns no row (RETURNING only reports rows it
        actually wrote), so a conflict is resolved with a plain SELECT of
        the row that already exists instead."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into sources "
                    "(canonical_url, domain, tier, title, http_status, storage_path) "
                    "values (%s, %s, %s, %s, %s, %s) "
                    "on conflict (canonical_url) do nothing "
                    "returning id",
                    (canonical_url, domain, tier, title, http_status, storage_path),
                )
                row = await cur.fetchone()
                if row is None:
                    await cur.execute(
                        "select id from sources where canonical_url = %s",
                        (canonical_url,))
                    row = await cur.fetchone()
                return _row_id(row)


class EvidenceRepo:
    """Insert-only, by construction of this class's method set (P6). See the
    module docstring for the full reasoning; do not add an update, delete,
    upsert, save, or set_* method here -- corrections belong in a new row
    with `superseded_by` pointing backwards at the row it replaces, exactly
    as 0003_immutability.sql's comment describes for the schema itself.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def insert_verified(self, project_id: str, run_id: str, assumption_id: str,
                              source_id: str, verified: VerifiedClaim) -> str | None:
        """Returns the new row's id, or None if `(project_id, dedup_hash)`
        already exists (P10) -- a duplicate is a no-op, never an exception.

        The insert runs inside a savepoint (`conn.transaction()`, nested
        automatically since the connection is already mid-transaction): a
        `UniqueViolation` aborts a plain transaction block until it is
        rolled back, and this repository has no business rolling back
        work a caller may have done earlier on the same connection just
        because one insert of several collided. The savepoint confines the
        rollback to exactly this insert.
        """
        claim = verified.claim
        computed_hash = dedup_hash(verified.canonical_url, claim.variable, claim.scope)
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "insert into evidence_items "
                            "(project_id, run_id, assumption_id, source_id, chair, "
                            "direction, variable, value_num, value_min, value_max, unit, "
                            "scope_geo, scope_segment, scope_tier, scope_period, "
                            "confidence, excerpt, dedup_hash) "
                            "values (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, "
                            "%s,%s,%s,%s, %s,%s,%s) "
                            "returning id",
                            (project_id, run_id, assumption_id, source_id, claim.chair.value,
                             claim.direction.value, claim.variable, claim.value_num,
                             claim.value_min, claim.value_max, claim.unit,
                             claim.scope.geo.value, claim.scope.segment.value,
                             claim.scope.tier.value if claim.scope.tier else None,
                             claim.scope.period,
                             claim.confidence, claim.excerpt, computed_hash),
                        )
                        row = await cur.fetchone()
                return _row_id(row)
        except psycopg.errors.UniqueViolation:
            return None

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from evidence_items where project_id = %s "
                    "order by created_at", (project_id,))
                return await cur.fetchall()

    async def list_for_conflict_engine(self, project_id: str, run_id: str) -> list[dict]:
        """Evidence rows for one run, joined to `sources` for `tier` --
        `evidence_items` itself carries no tier column (PRD §16.2: tier is a
        property of the source, assigned once when it is first fetched, not
        re-derived per citing claim). `jury.engines.conflict` needs tier on
        every item it compares, so the join happens here rather than forcing
        every caller to fetch sources separately."""
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select e.*, s.tier as source_tier from evidence_items e "
                    "join sources s on s.id = e.source_id "
                    "where e.project_id = %s and e.run_id = %s "
                    "order by e.created_at", (project_id, run_id))
                return await cur.fetchall()


class AssumptionRepo:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def create_many(self, project_id: str, run_id: str,
                          assumptions: list[dict]) -> list[str]:
        """Bulk-insert founder-origin assumptions extracted from the hearing
        (PRD §7.2). Each dict supplies at least `statement`, `criticality`,
        `uncertainty`, `falsifiability`; `class_key`/`asserted_variable`/
        `asserted_value`/`asserted_unit` are optional (a founder assertion
        that carries no number is still an assumption, and a founder-added
        assumption from the hearing UI -- PRD §7.3's "the founder can add
        their own" -- may not have been classified against the checklist at
        all). `class_key` is read with `.get`, not `[...]`, for exactly that
        reason: Task 4.3's own hearing-resume path passes founder-added
        assumptions through this method with no `class_key` key present at
        all, not merely one set to `None`."""
        ids = []
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                for a in assumptions:
                    await cur.execute(
                        "insert into assumptions "
                        "(project_id, run_id, class_key, statement, origin, "
                        "criticality, uncertainty, falsifiability, "
                        "asserted_variable, asserted_value, asserted_unit) "
                        "values (%s,%s,%s,%s,'founder', %s,%s,%s, %s,%s,%s) "
                        "returning id",
                        (project_id, run_id, a.get("class_key"), a["statement"],
                         a["criticality"], a["uncertainty"], a["falsifiability"],
                         a.get("asserted_variable"), a.get("asserted_value"),
                         a.get("asserted_unit")),
                    )
                    ids.append(_row_id(await cur.fetchone()))
        return ids

    async def create_discovered(self, project_id: str, run_id: str, chair: str,
                                class_key: str, statement: str, criticality: str,
                                uncertainty: str, falsifiability: str) -> str:
        """A chair introducing an assumption the extractor missed (PRD §7.3);
        `discovered_by` must name the chair (schema's
        `discovered_by_matches_origin` check)."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into assumptions "
                    "(project_id, run_id, class_key, statement, origin, discovered_by, "
                    "criticality, uncertainty, falsifiability) "
                    "values (%s,%s,%s,%s,'discovered',%s, %s,%s,%s) "
                    "returning id",
                    (project_id, run_id, class_key, statement, chair,
                     criticality, uncertainty, falsifiability),
                )
                return _row_id(await cur.fetchone())

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from assumptions where project_id = %s "
                    "order by created_at", (project_id,))
                return await cur.fetchall()

    async def update_status_and_strength(self, assumption_id: str, status: str,
                                         strength: float) -> None:
        """Unlike evidence, an assumption's status/strength is a live
        rollup recomputed as evidence arrives -- there is no immutability
        constraint on `assumptions` in the schema, and the brief names this
        method explicitly, so a direct UPDATE is the intended shape here."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "update assumptions set status = %s, strength = %s where id = %s",
                    (status, strength, assumption_id),
                )


class ProjectRepo:
    """Task 4.4. `projects` is the top-level object the API exposes; every
    write here is expected to run through a connection already switched to
    `authenticated` for the owning user (`jury.db.pool.user_scoped_connection`)
    so RLS is the actual access-control boundary, not this class's own logic.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, user_id: str, name: str, target_scope: dict,
                     archetype: str | None = None) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "insert into projects (user_id, name, archetype, target_scope) "
                    "values (%s,%s,%s,%s) returning *",
                    (user_id, name, archetype, Json(target_scope)),
                )
                return await cur.fetchone()

    async def get(self, project_id: str) -> dict | None:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("select * from projects where id = %s", (project_id,))
                return await cur.fetchone()

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from projects where user_id = %s order by created_at",
                    (user_id,))
                return await cur.fetchall()

    async def update(self, project_id: str, *, archetype: str | None = None,
                     target_scope: dict | None = None,
                     name: str | None = None) -> dict | None:
        """Patch only the fields actually supplied (PRD §13: archetype is
        user-overridable). Nothing here bypasses RLS -- an update against a
        project the caller's role cannot see simply matches zero rows."""
        sets, params = [], []
        if archetype is not None:
            sets.append("archetype = %s")
            params.append(archetype)
        if target_scope is not None:
            sets.append("target_scope = %s")
            params.append(Json(target_scope))
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if not sets:
            return await self.get(project_id)
        sets.append("updated_at = now()")
        params.append(project_id)
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"update projects set {', '.join(sets)} where id = %s returning *",
                    params,
                )
                return await cur.fetchone()


class PitchRepo:
    """`pitches` records the founder's raw intake text and any uploaded
    artifact metadata (PRD §17.4). No update method: a pitch is what the
    founder submitted at intake, and `artifacts` is append-only via
    `add_artifact`'s `jsonb ||` concatenation, never a wholesale replace."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, project_id: str, body: str) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into pitches (project_id, body) values (%s, %s) "
                    "returning id",
                    (project_id, body),
                )
                return _row_id(await cur.fetchone())

    async def add_artifact(self, project_id: str, artifact: dict) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "update pitches set artifacts = artifacts || %s::jsonb "
                    "where project_id = %s and id = "
                    "(select id from pitches where project_id = %s "
                    "order by created_at desc limit 1)",
                    (Json([artifact]), project_id, project_id),
                )


class RunRepo:
    """Task 4.4. `runs` tracks the graph's own progress; `status` only ever
    takes one of the schema's CHECK values (`pending|hearing|investigating|
    cross_exam|deciding|complete|failed`) -- a chair degrading to partial
    evidence (PRD §18) is tracked in the graph's own `RunState.run_status`
    (jury/graph/state.py), never written here as a run status, since
    'partial' is not one of the values the CHECK constraint allows."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, project_id: str, user_id: str, thread_id: str,
                     kind: str = "initial") -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "insert into runs (project_id, user_id, kind, status, thread_id) "
                    "values (%s,%s,%s,'pending',%s) returning *",
                    (project_id, user_id, kind, thread_id),
                )
                return await cur.fetchone()

    async def get(self, run_id: str) -> dict | None:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("select * from runs where id = %s", (run_id,))
                return await cur.fetchone()

    async def update_status(self, run_id: str, status: str) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                completed = ", completed_at = now()" if status in ("complete", "failed") else ""
                await cur.execute(
                    f"update runs set status = %s{completed} where id = %s",
                    (status, run_id),
                )

    async def list_events(self, run_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from run_events where run_id = %s order by ts, id",
                    (run_id,))
                return await cur.fetchall()


class ConflictRepo:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, project_id: str, run_id: str, assumption_id: str,
                     kind: str, left_ref: dict, right_ref: dict | None,
                     rule: str, severity: str) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into conflicts "
                    "(project_id, run_id, assumption_id, kind, left_ref, right_ref, "
                    "rule, severity) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (project_id, run_id, assumption_id, kind,
                     Json(left_ref),
                     Json(right_ref) if right_ref is not None else None,
                     rule, severity),
                )
                return _row_id(await cur.fetchone())

    async def add_position_delta(self, conflict_id: str, chair: str, before: str,
                                 after: str, reason: str,
                                 new_evidence_id: str | None = None) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into position_deltas "
                    "(conflict_id, chair, before, after, reason, new_evidence_id) "
                    "values (%s,%s,%s,%s,%s,%s) returning id",
                    (conflict_id, chair, before, after, reason, new_evidence_id),
                )
                return _row_id(await cur.fetchone())

    async def resolve(self, conflict_id: str, status: str, resolution: str) -> None:
        """`conflicts.status` is designed to transition (open -> resolved /
        conceded / unresolvable, PRD §12); no P6-style immutability applies
        to this table, so a direct UPDATE is correct here."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "update conflicts set status = %s, resolution = %s where id = %s",
                    (status, resolution, conflict_id),
                )

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from conflicts where project_id = %s "
                    "order by created_at", (project_id,))
                return await cur.fetchall()


class ModelRunRepo:
    """`model_runs` is an append-only log of computed economics scenarios;
    nothing in PRD §16.5 revises a scenario in place, so this repo is
    read/insert only, the same shape as `EvidenceRepo` but without the
    dedup concern (there is no cross-run identity to collide on)."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, project_id: str, run_id: str, template_key: str,
                     parameters: dict, outputs: dict, breakpoints: dict,
                     sensitivity: dict, viable: bool) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into model_runs "
                    "(project_id, run_id, template_key, parameters, outputs, "
                    "breakpoints, sensitivity, viable) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (project_id, run_id, template_key,
                     Json(parameters),
                     Json(outputs),
                     Json(breakpoints),
                     Json(sensitivity), viable),
                )
                return _row_id(await cur.fetchone())

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from model_runs where project_id = %s "
                    "order by created_at", (project_id,))
                return await cur.fetchall()


class ExperimentRepo:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, project_id: str, assumption_id: str,
                     target_variable: str | None, method: str, instructions: str,
                     kill_criterion: str, criterion_spec: dict,
                     est_cost: float | None, est_days: int | None,
                     priority: int) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into experiments "
                    "(project_id, assumption_id, target_variable, method, instructions, "
                    "kill_criterion, criterion_spec, est_cost, est_days, priority) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (project_id, assumption_id, target_variable, method, instructions,
                     kill_criterion, Json(criterion_spec),
                     est_cost, est_days, priority),
                )
                return _row_id(await cur.fetchone())

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from experiments where project_id = %s "
                    "order by priority", (project_id,))
                return await cur.fetchall()

    async def log_result(self, experiment_id: str, status: str,
                         result_value: float | None, result_notes: str | None) -> None:
        """An experiment's status/result is filled in after it actually runs
        (PRD §16.6); like assumptions and conflicts, this is a live-status
        table, not an insert-only ledger, so UPDATE is correct here."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "update experiments set status = %s, result_value = %s, "
                    "result_notes = %s, logged_at = now() where id = %s",
                    (status, result_value, result_notes, experiment_id),
                )


class VerdictRepo:
    """`verdicts` is an append-only decision history: PRD §12 gives it no
    status column and no update path, so this repo is insert/read only."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, run_id: str, project_id: str, decision: str,
                     evidence_confidence: float, components: dict,
                     gate_triggered: str | None, friction: dict, rationale: str) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into verdicts "
                    "(run_id, project_id, decision, evidence_confidence, components, "
                    "gate_triggered, friction, rationale) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                    (run_id, project_id, decision, evidence_confidence,
                     Json(components), gate_triggered,
                     Json(friction), rationale),
                )
                return _row_id(await cur.fetchone())

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from verdicts where project_id = %s "
                    "order by created_at", (project_id,))
                return await cur.fetchall()


class LedgerVersionRepo:
    """`ledger_versions` is the append-only snapshot/diff history behind
    return-visit runs (PRD §9); `unique (project_id, version)` is the
    schema's own guarantee that a version number is never reused."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, project_id: str, run_id: str, version: int,
                     snapshot: dict, diff: dict) -> str:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "insert into ledger_versions (project_id, run_id, version, snapshot, diff) "
                    "values (%s,%s,%s,%s,%s) returning id",
                    (project_id, run_id, version, Json(snapshot),
                     Json(diff)),
                )
                return _row_id(await cur.fetchone())

    async def latest_for_project(self, project_id: str) -> dict | None:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "select * from ledger_versions where project_id = %s "
                    "order by version desc limit 1", (project_id,))
                return await cur.fetchone()
