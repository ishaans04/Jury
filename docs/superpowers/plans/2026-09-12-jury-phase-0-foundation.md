# Phase 0 — Foundation

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **Spec:** [`2026-09-12-jury-design.md`](../specs/2026-09-12-jury-design.md) · **PRD:** [`docs/PRD.md`](../../PRD.md) §12, §14.4, §21.4

**Phase goal:** A monorepo with the complete database schema, RLS, database-enforced evidence immutability, hand-seeded coverage denominator, and every Pydantic contract the rest of the build codes against.

**Why this order:** PRD §20 sequencing rule — *"Do not defer versioning to the end; retrofitting immutability onto a mutable schema is a rewrite, so insert-only evidence and snapshot-plus-diff go in at M0 even though the diff UI arrives at M6."* Every later phase writes rows; the constraints must exist before the first row.

**Gate:** `cd apps/api && uv run pytest -q` green, migrations applied to local Supabase, and `test_evidence_immutable_at_database_level` proving Postgres itself rejects `UPDATE evidence_items` — not application code.

---

## File structure

| Path | Responsibility |
|---|---|
| `.gitignore` | Exclude `.env`, `.venv`, `node_modules`, `.next`, `__pycache__`, `supabase/.temp` |
| `.env.example` | Every key from PRD §21.2, names only, empty values |
| `README.md` | Placeholder until Phase 7; must not be empty |
| `CHANGELOG.md` | Running context anchor |
| `package.json` | npm workspace root (`apps/web`) |
| `supabase/config.toml` | Supabase CLI local config |
| `supabase/migrations/0001_schema.sql` | All **17** tables verbatim from PRD §12 |
| `supabase/migrations/0002_rls.sql` | RLS policies per PRD §14.4 |
| `supabase/migrations/0003_immutability.sql` | Evidence UPDATE/DELETE denial for all roles |
| `supabase/migrations/0004_position_deltas_chair_check.sql` | Missing chair enum CHECK (controller ruling) |
| `db/README.md` | Pointer: migrations live under `supabase/migrations/` (deviation **D8**) |
| `db/seed/001_assumption_classes.sql` | 45 hand-authored rows (P4) |
| `db/seed/002_domain_tiers.sql` | Domain → tier map for PRD §16.2 |
| `apps/api/pyproject.toml` | uv project, Python 3.12 pin, deps |
| `apps/api/.python-version` | `3.12` |
| `apps/api/jury/schemas/enums.py` | All closed sets as `StrEnum` |
| `apps/api/jury/schemas/scope.py` | `Scope` model |
| `apps/api/jury/schemas/claim.py` | `ClaimRecord` — the chair output contract (PRD §6.1) |
| `apps/api/jury/schemas/assumption.py` | `AssumptionDraft`, `AssumptionRecord` |
| `apps/api/jury/schemas/economics.py` | `Parameter`, `Breakpoint`, `SensitivityEntry`, `ModelOutputs` |
| `apps/api/jury/schemas/experiment.py` | `CriterionSpec`, `ExperimentDraft` |
| `apps/api/jury/schemas/verdict.py` | `ConfidenceComponents`, `VerdictRecord` |
| `apps/api/jury/settings.py` | Pydantic-settings; **all external keys optional** |
| `apps/api/tests/conftest.py` | DB fixture against local Supabase |
| `apps/api/tests/test_schema_contracts.py` | Contract round-trip + rejection tests |
| `apps/api/tests/test_db_constraints.py` | Immutability + dedup uniqueness + tier-5 rejection |
| `apps/api/tests/test_seed_integrity.py` | Coverage denominator integrity |

---

### Task 0.1: Repository skeleton and tooling

**Files:**
- Create: `.gitignore`, `.env.example`, `CHANGELOG.md`, `README.md`, `package.json`
- Create: `apps/api/pyproject.toml`, `apps/api/.python-version`, `apps/api/jury/__init__.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: a `uv` environment at `apps/api/.venv` on Python 3.12 with `pytest` runnable via `uv run pytest`

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/

# node
node_modules/
.next/
out/
.turbo/

# env — never commit real keys
.env
.env.local
.env*.local

# supabase local
supabase/.temp/
supabase/.branches/

# os
.DS_Store
Thumbs.db
```

- [ ] **Step 2: Write `.env.example` — every key named, every value empty**

Per the user's explicit instruction: label the key names and leave them empty.

```bash
# ── Supabase ────────────────────────────────────────────────
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=

# ── LLM (single provider, overridable — PRD §15.2) ─────────
LLM_PROVIDER=groq
GROQ_API_KEY=
LLM_MODEL_REASONING=
LLM_MODEL_FAST=
LLM_MODEL_FALLBACK=

# ── Retrieval ──────────────────────────────────────────────
BRAVE_API_KEY=
TAVILY_API_KEY=
EXA_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
PRODUCTHUNT_TOKEN=
# HN Algolia and Wayback CDX need no key (PRD §11.1)

# ── Infra ──────────────────────────────────────────────────
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
DATABASE_URL=

# ── App ────────────────────────────────────────────────────
APP_BASE_URL=

# ── Build mode ─────────────────────────────────────────────
# 1 = all external transport served from recorded fixtures (spec §3)
JURY_OFFLINE=1
```

Note: `QDRANT_URL` / `QDRANT_API_KEY` / `RENDER_SERVICE_URL` are **absent** — Qdrant and the Playwright service are cut per spec §4.

- [ ] **Step 3: Write `apps/api/.python-version` and `pyproject.toml`**

`apps/api/.python-version`:
```
3.12
```

`apps/api/pyproject.toml`:
```toml
[project]
name = "jury-api"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "psycopg[binary,pool]>=3.2",
  "sqlalchemy>=2.0",
  "langgraph>=0.2.45",
  "langgraph-checkpoint-postgres>=2.0",
  "litellm>=1.52",
  "httpx>=0.27",
  "trafilatura>=1.12",
  "numpy>=2.1",
  "scipy>=1.14",
  "fastembed>=0.4",
  "python-jose[cryptography]>=3.3",
  "tenacity>=9.0",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.7", "respx>=0.21"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 4: Create the environment and verify the Python pin**

```bash
cd apps/api && uv python pin 3.12 && uv sync --dev
uv run python -c "import sys; assert sys.version_info[:2]==(3,12), sys.version; print('py', sys.version)"
```
Expected: prints `py 3.12.x`. If uv reports no 3.12 available, `uv python install 3.12` first.

- [ ] **Step 5: Write `package.json` workspace root**

```json
{
  "name": "jury",
  "private": true,
  "workspaces": ["apps/web"],
  "scripts": {
    "dev": "npm run dev --workspace apps/web",
    "build": "npm run build --workspace apps/web",
    "test": "npm run test --workspace apps/web"
  }
}
```

- [ ] **Step 6: Seed `CHANGELOG.md`**

```markdown
# Changelog

Running record of what has actually been built. Re-read in full before each phase
(alongside `docs/PRD.md` and `docs/superpowers/specs/2026-09-12-jury-design.md`).

Every entry records: what was built, the gate command, its **actual** output, and
**any deviation from PRD.md with its reason**. Drift that is written down is a
decision; drift that is not is a bug.

## [Unreleased]

### Phase 0 — Foundation
- _in progress_
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: monorepo skeleton, python 3.12 pin, env template"
```

---

### Task 0.2: Database schema migration

**Files:**
- Create: `supabase/migrations/0001_schema.sql`
- Create: `supabase/config.toml` (via `supabase init`)

**Interfaces:**
- Consumes: Task 0.1's repo layout
- Produces: 15 tables. Downstream tasks reference these exact column names.

- [ ] **Step 1: Initialise Supabase locally**

```bash
npx --yes supabase@latest init
npx --yes supabase@latest start
```
Expected: prints local `API URL`, `DB URL`, `anon key`, `service_role key`. Record the DB URL — it is `postgresql://postgres:postgres@127.0.0.1:54322/postgres`.

- [ ] **Step 2: Write `supabase/migrations/0001_schema.sql`**

Transcribed from PRD §12 with **no structural changes**. Two additions flagged in comments.

```sql
-- Jury schema. Source: PRD §12.
create extension if not exists vector;
create extension if not exists pgcrypto;

-- ========== identity & ownership ==========
create table profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  email         text not null,
  created_at    timestamptz default now()
);

create table projects (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null,
  archetype     text check (archetype in
                  ('marketplace','subscription_saas','d2c','services','ad_consumer','hardware')),
  target_scope  jsonb not null,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create table runs (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  user_id       uuid not null references auth.users(id) on delete cascade,
  kind          text not null check (kind in ('initial','return_visit','pivot_check')),
  status        text not null check (status in
                  ('pending','hearing','investigating','cross_exam','deciding','complete','failed')),
  thread_id     text not null,
  started_at    timestamptz default now(),
  completed_at  timestamptz
);

create table pitches (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  body          text not null check (length(body) between 200 and 2000),
  artifacts     jsonb default '[]',
  created_at    timestamptz default now()
);

-- ========== the coverage denominator (hand-seeded, never LLM-generated: P4) ==========
create table assumption_classes (
  key           text primary key,
  archetype     text not null,
  label         text not null,
  question      text not null,
  crit_weight   numeric not null check (crit_weight in (1.0, 0.6, 0.3))
);

-- ========== assumptions: propositions, not evidence (P2) ==========
create table assumptions (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid references runs(id),
  class_key     text references assumption_classes(key),
  statement     text not null,
  origin        text not null check (origin in ('founder','discovered')),
  discovered_by text check (discovered_by in
                  ('market','customer','precedent','dependencies','economics')),
  criticality   text not null check (criticality in ('blocking','high','medium','low')),
  uncertainty   text not null check (uncertainty in
                  ('unknown','uncertain','likely','established')),
  falsifiability text not null check (falsifiability in
                  ('testable_now','testable_costly','untestable')),
  asserted_variable text,
  asserted_value    numeric,
  asserted_unit     text,
  status        text not null default 'no_evidence' check (status in
                  ('no_evidence','uncertain','supported','refuted','contested')),
  strength      numeric default 0 check (strength between 0 and 1),
  superseded_by uuid references assumptions(id),
  created_at    timestamptz default now(),
  -- ADDITION (not in PRD §12): P2 integrity. discovered_by is meaningful only
  -- when origin='discovered', and a discovered assumption must name its chair.
  constraint discovered_by_matches_origin check (
    (origin = 'discovered' and discovered_by is not null) or
    (origin = 'founder'    and discovered_by is null)
  )
);

-- ========== sources ==========
create table sources (
  id            uuid primary key default gen_random_uuid(),
  canonical_url text not null,
  domain        text not null,
  tier          int  not null check (tier between 1 and 4),  -- tier 5 cannot exist (P1)
  title         text,
  retrieved_at  timestamptz not null default now(),
  http_status   int  not null check (http_status between 200 and 299),  -- P1: 2xx only
  storage_path  text,
  unique (canonical_url)
);

-- ========== evidence: insert-only, source-backed (P1, P6, P10) ==========
create table evidence_items (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid not null references runs(id),
  assumption_id uuid not null references assumptions(id) on delete cascade,
  source_id     uuid not null references sources(id),
  chair         text not null check (chair in
                  ('market','customer','precedent','dependencies','economics')),
  direction     text not null check (direction in ('supports','refutes')),
  variable      text,
  value_num     numeric,
  value_min     numeric,
  value_max     numeric,
  unit          text,
  scope_geo     text not null check (scope_geo in
                  ('IN','US','EU','UK','SEA','MENA','LATAM','GLOBAL')),
  scope_segment text not null check (scope_segment in
                  ('consumer','prosumer','smb','mid_market','enterprise','public_sector')),
  scope_tier    text check (scope_tier in ('free','entry','mid','premium','enterprise')),
  scope_period  text,
  confidence    numeric not null check (confidence between 0 and 1),
  excerpt       text not null check (length(excerpt) <= 240),
  dedup_hash    text not null,
  superseded_by uuid references evidence_items(id),
  created_at    timestamptz default now(),
  unique (project_id, dedup_hash)   -- P10
);

create index on evidence_items (assumption_id);
create index on evidence_items (run_id, chair);

-- ========== retrieval ==========
create table source_chunks (
  id            uuid primary key default gen_random_uuid(),
  source_id     uuid not null references sources(id) on delete cascade,
  chunk_index   int not null,
  content       text not null,
  embedding     vector(384)
);
create index on source_chunks using hnsw (embedding vector_cosine_ops);

-- ========== conflicts ==========
create table conflicts (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid not null references runs(id),
  assumption_id uuid not null references assumptions(id) on delete cascade,
  kind          text not null check (kind in
                  ('founder_vs_world','chair_vs_chair','no_evidence','scope_gap')),
  left_ref      jsonb not null,
  right_ref     jsonb,
  rule          text not null check (rule in ('R1','R2','R3','R4','R5')),
  severity      text not null check (severity in ('critical','high','medium','low')),
  status        text not null default 'open' check (status in
                  ('open','resolved','conceded','unresolvable')),
  resolution    text,
  created_at    timestamptz default now()
);

create table position_deltas (
  id            uuid primary key default gen_random_uuid(),
  conflict_id   uuid not null references conflicts(id) on delete cascade,
  chair         text not null,
  before        text not null,
  after         text not null,
  reason        text not null,
  new_evidence_id uuid references evidence_items(id)
);

-- ========== economics ==========
create table model_runs (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid not null references runs(id),
  template_key  text not null,
  parameters    jsonb not null,
  outputs       jsonb not null,
  breakpoints   jsonb not null,
  sensitivity   jsonb not null,
  viable        boolean not null,
  created_at    timestamptz default now()
);

-- ========== experiments ==========
create table experiments (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references projects(id) on delete cascade,
  assumption_id   uuid not null references assumptions(id) on delete cascade,
  target_variable text,
  method          text not null,
  instructions    text not null,
  kill_criterion  text not null,          -- P9
  criterion_spec  jsonb not null,         -- P9, machine-evaluable
  est_cost        numeric,
  est_days        int,
  priority        int not null,
  status          text not null default 'proposed' check (status in
                    ('proposed','running','passed','failed','abandoned')),
  result_value    numeric,
  result_notes    text,
  logged_at       timestamptz
);

-- ========== verdicts & versions ==========
create table verdicts (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references runs(id) on delete cascade,
  project_id    uuid not null references projects(id) on delete cascade,
  decision      text not null check (decision in ('PROCEED','PIVOT','STOP','HUNG_JURY')),
  evidence_confidence numeric not null check (evidence_confidence between 0 and 100),
  components    jsonb not null,
  gate_triggered text,
  friction      jsonb not null,
  rationale     text not null,
  created_at    timestamptz default now()
);

create table ledger_versions (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  version       int not null,
  run_id        uuid not null references runs(id),
  snapshot      jsonb not null,
  diff          jsonb not null,
  created_at    timestamptz default now(),
  unique (project_id, version)
);

-- ========== in-app tracing (replaces external observability: PRD §11.2 dec. 9) ==========
create table run_events (
  id            bigserial primary key,
  run_id        uuid not null references runs(id) on delete cascade,
  ts            timestamptz default now(),
  node          text not null,
  event         text not null check (event in
                  ('node_start','node_end','llm_call','tool_call','fetch','error','interrupt')),
  detail        jsonb,
  latency_ms    int
);
create index on run_events (run_id, ts);
```

- [ ] **Step 3: Apply and verify table count**

```bash
npx --yes supabase@latest db reset
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "\dt public.*" | grep -c table
```
Expected: **17** public tables (16 from this migration plus `domain_tiers` from Task 0.5).
If `psql` is not on PATH, run the same count through a short `psycopg` script — do not skip the verification.

- [ ] **Step 4: Commit**

```bash
git add supabase supabase/migrations/0001_schema.sql
git commit -m "feat(db): full ledger schema with enum and range constraints"
```

---

### Task 0.3: RLS and database-enforced evidence immutability

**Files:**
- Create: `supabase/migrations/0002_rls.sql`
- Create: `supabase/migrations/0003_immutability.sql`
- Test: `apps/api/tests/test_db_constraints.py`

**Interfaces:**
- Consumes: `0001_schema.sql` tables
- Produces: a database where P6 holds against the **service role**, not just the app

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_db_constraints.py`:
```python
import psycopg
import pytest

DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


@pytest.fixture()
def conn():
    with psycopg.connect(DSN, autocommit=True) as c:
        yield c


def _seed_minimal(conn):
    """Create the FK chain an evidence row needs.

    Returns (evidence_id, project_id, run_id, assumption_id, source_id).

    NOTE: auth.users is managed by Supabase Auth and has NOT NULL columns
    beyond id/email. Verify the actual NOT NULL set against the running local
    database and extend this insert if it rejects — do not guess.
    """
    with conn.cursor() as cur:
        cur.execute(
            "insert into auth.users (instance_id, id, aud, role, email, "
            " encrypted_password, created_at, updated_at) "
            "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
            " 'authenticated', 'authenticated', "
            " 'p0-' || gen_random_uuid() || '@test.local', '', now(), now()) "
            "returning id")
        user_id = cur.fetchone()[0]

        cur.execute("insert into projects (user_id, name, target_scope) values (%s,'p','{}') "
                    "returning id", (user_id,))
        project_id = cur.fetchone()[0]
        cur.execute("insert into runs (project_id, user_id, kind, status, thread_id) "
                    "values (%s,%s,'initial','pending','t1') returning id", (project_id, user_id))
        run_id = cur.fetchone()[0]
        cur.execute("insert into assumptions (project_id, run_id, statement, origin, criticality,"
                    " uncertainty, falsifiability) values (%s,%s,'s','founder','blocking',"
                    "'unknown','testable_now') returning id", (project_id, run_id))
        assumption_id = cur.fetchone()[0]
        cur.execute("insert into sources (canonical_url, domain, tier, http_status) "
                    "values ('https://x.test/p','x.test',1,200) returning id")
        source_id = cur.fetchone()[0]
        cur.execute(
            "insert into evidence_items (project_id, run_id, assumption_id, source_id, chair,"
            " direction, scope_geo, scope_segment, confidence, excerpt, dedup_hash)"
            " values (%s,%s,%s,%s,'market','supports','IN','smb',0.8,'e','h1') returning id",
            (project_id, run_id, assumption_id, source_id))
        return cur.fetchone()[0], project_id, run_id, assumption_id, source_id


def test_evidence_immutable_at_database_level(conn):
    """P6: corrections supersede, never update. Enforced by Postgres, not app code."""
    ev_id, *_ = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("update evidence_items set confidence = 0.1 where id = %s", (ev_id,))


def test_evidence_undeletable_at_database_level(conn):
    ev_id, *_ = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute("delete from evidence_items where id = %s", (ev_id,))


def test_dedup_hash_unique_per_project(conn):
    """P10: the same source twice never inflates confidence."""
    _, project_id, run_id, assumption_id, source_id = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into evidence_items (project_id, run_id, assumption_id, source_id, chair,"
                " direction, scope_geo, scope_segment, confidence, excerpt, dedup_hash)"
                " values (%s,%s,%s,%s,'customer','supports','IN','smb',0.9,'e2','h1')",
                (project_id, run_id, assumption_id, source_id))


def test_tier_five_source_rejected(conn):
    """P1: tier 5 is a model prior, not evidence. It cannot be persisted."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute("insert into sources (canonical_url, domain, tier, http_status) "
                        "values ('https://y.test/p','y.test',5,200)")


def test_non_2xx_source_rejected(conn):
    """P1: no fetched 2xx, no source row."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute("insert into sources (canonical_url, domain, tier, http_status) "
                        "values ('https://z.test/p','z.test',1,403)")


def test_discovered_assumption_must_name_a_chair(conn):
    _, project_id, run_id, *_ = _seed_minimal(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute("insert into assumptions (project_id, run_id, statement, origin,"
                        " criticality, uncertainty, falsifiability) values"
                        " (%s,%s,'s','discovered','high','unknown','testable_now')",
                        (project_id, run_id))
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/test_db_constraints.py -v
```
Expected: `test_evidence_immutable_at_database_level` FAILS — the UPDATE currently succeeds because no revocation exists.

- [ ] **Step 3: Write `supabase/migrations/0002_rls.sql`**

```sql
-- RLS per PRD §14.4. Every user-owned table authorises through its project.
alter table profiles        enable row level security;
alter table projects        enable row level security;
alter table runs            enable row level security;
alter table pitches         enable row level security;
alter table assumptions     enable row level security;
alter table evidence_items  enable row level security;
alter table source_chunks   enable row level security;
alter table conflicts       enable row level security;
alter table position_deltas enable row level security;
alter table model_runs      enable row level security;
alter table experiments     enable row level security;
alter table verdicts        enable row level security;
alter table ledger_versions enable row level security;
alter table run_events      enable row level security;
alter table sources         enable row level security;
alter table assumption_classes enable row level security;

create policy "own profile" on profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy "own projects" on projects
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Child tables authorise through the project.
do $$
declare t text;
begin
  foreach t in array array['runs','pitches','assumptions','evidence_items','conflicts',
                           'model_runs','experiments','verdicts','ledger_versions']
  loop
    execute format($f$
      create policy "own %1$s" on %1$I for all using (
        exists (select 1 from projects p where p.id = %1$I.project_id and p.user_id = auth.uid())
      ) with check (
        exists (select 1 from projects p where p.id = %1$I.project_id and p.user_id = auth.uid())
      )$f$, t);
  end loop;
end $$;

-- Grandchildren authorise through their parent.
create policy "own position_deltas" on position_deltas for all using (
  exists (select 1 from conflicts c join projects p on p.id = c.project_id
          where c.id = position_deltas.conflict_id and p.user_id = auth.uid())
);

create policy "own run_events" on run_events for all using (
  exists (select 1 from runs r join projects p on p.id = r.project_id
          where r.id = run_events.run_id and p.user_id = auth.uid())
);

create policy "own source_chunks" on source_chunks for all using (
  exists (select 1 from evidence_items e join projects p on p.id = e.project_id
          where e.source_id = source_chunks.source_id and p.user_id = auth.uid())
);

-- PRD §14.4: sources are deliberately shared and globally deduplicated. A fetched
-- pricing page is not private data, and a shared cache reduces search quota burn.
-- Nothing user-identifying is stored on the row.
create policy "sources readable by all authenticated" on sources
  for select using (auth.role() = 'authenticated');

-- P4: the coverage denominator is public read-only reference data.
create policy "classes readable by all" on assumption_classes
  for select using (true);
```

- [ ] **Step 4: Write `supabase/migrations/0003_immutability.sql`**

This is the migration that makes P6 real. Revocation covers `service_role` too, which is the part application code cannot achieve.

```sql
-- P6: evidence is immutable. Corrections happen by superseding, never by updating.
-- PRD §14.4: "evidence_items additionally denies UPDATE and DELETE to all roles
-- including the service role, enforcing P6 at the database level rather than in
-- application code."

-- TRUNCATE must be revoked alongside UPDATE/DELETE. It bypasses RLS entirely
-- (FORCE ROW LEVEL SECURITY does not apply to it) and fires no row-level
-- trigger, so without this line service_role can wipe the whole ledger in one
-- statement and cascade into position_deltas.
-- DELETE is deliberately NOT revoked from the table owner. Referential actions
-- run as the owner, and evidence_items.project_id is declared ON DELETE CASCADE,
-- so revoking DELETE from the owner makes it impossible to delete a project or
-- an auth user at all -- the FK check needs a KEY SHARE lock on this table.
-- P6 protects against CORRECTIONS silently rewriting history; erasing a whole
-- project at the owner's request falsifies nothing. So UPDATE and TRUNCATE stay
-- shut for everyone, and DELETE is reachable only as a cascade.
revoke update, truncate on evidence_items
  from anon, authenticated, service_role, postgres;
revoke delete on evidence_items
  from anon, authenticated, service_role;

alter table evidence_items force row level security;   -- applies RLS to the table owner

create policy "evidence insert own" on evidence_items for insert with check (
  exists (select 1 from projects p where p.id = evidence_items.project_id
          and p.user_id = auth.uid())
);
create policy "evidence select own" on evidence_items for select using (
  exists (select 1 from projects p where p.id = evidence_items.project_id
          and p.user_id = auth.uid())
);
-- Deliberately NO update or delete policy exists. Combined with the REVOKE above,
-- there is no grant path to mutate a row.

-- Belt and braces: a trigger that raises even if a future migration re-grants.
create or replace function jury_evidence_is_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'evidence_items is insert-only (P6); correct by inserting a '
                  'superseding row and setting superseded_by';
end $$;

create trigger evidence_no_update before update on evidence_items
  for each row execute function jury_evidence_is_immutable();
-- No BEFORE DELETE trigger: it would block the project/user erasure cascade
-- unconditionally. DELETE is already unreachable from every application role
-- via the REVOKE above.
-- TRUNCATE triggers are statement-level only; FOR EACH ROW is rejected here.
-- This is what stops a genuine superuser (supabase_admin), which bypasses
-- the REVOKE above.
create trigger evidence_no_truncate before truncate on evidence_items
  for each statement execute function jury_evidence_is_immutable();
```

Note: the `superseded_by` pointer is set on the **superseded** row, which an insert-only table cannot do. Resolution: `superseded_by` is written on the **new** row pointing *backwards* at the row it replaces. This inverts PRD §12's implied direction and is recorded as a deviation in `CHANGELOG.md`. Readers resolve "current" as *rows not referenced by any other row's `superseded_by`*.

- [ ] **Step 5: Apply and run the tests**

```bash
npx --yes supabase@latest db reset
cd apps/api && uv run pytest tests/test_db_constraints.py -v
```
Expected: all 6 PASS. The immutability tests now raise from the trigger.

If the trigger raises `RaiseException` rather than `InsufficientPrivilege`, widen the test's expected exception to `psycopg.errors.RaiseException` — the *behaviour* under test is rejection, not the SQLSTATE.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0002_rls.sql supabase/migrations/0003_immutability.sql apps/api/tests/test_db_constraints.py
git commit -m "feat(db): RLS on every table and database-enforced evidence immutability"
```

---

### Task 0.4: Seed the coverage denominator

**Files:**
- Create: `db/seed/001_assumption_classes.sql`
- Test: `apps/api/tests/test_seed_integrity.py`

**Interfaces:**
- Consumes: `assumption_classes` table
- Produces: 45 rows — 3 archetypes × 10, 3 archetypes × 5

**Why hand-authored:** PRD §25 names "coverage score becomes self-graded" as High severity and says *"`assumption_classes` is hand-seeded static data. Never generate it at runtime. This is the one shortcut that would hollow out the whole product."*

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_seed_integrity.py`:
```python
import psycopg
import pytest

DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DEEP = {"marketplace", "subscription_saas", "d2c"}
SHALLOW = {"services", "ad_consumer", "hardware"}


@pytest.fixture()
def conn():
    with psycopg.connect(DSN, autocommit=True) as c:
        yield c


def test_all_six_archetypes_seeded(conn):
    with conn.cursor() as cur:
        cur.execute("select distinct archetype from assumption_classes")
        assert {r[0] for r in cur.fetchall()} == DEEP | SHALLOW


def test_deep_archetypes_have_ten_classes(conn):
    with conn.cursor() as cur:
        cur.execute("select archetype, count(*) from assumption_classes "
                    "where archetype = any(%s) group by archetype", (list(DEEP),))
        assert dict(cur.fetchall()) == {a: 10 for a in DEEP}


def test_shallow_archetypes_have_five_classes(conn):
    with conn.cursor() as cur:
        cur.execute("select archetype, count(*) from assumption_classes "
                    "where archetype = any(%s) group by archetype", (list(SHALLOW),))
        assert dict(cur.fetchall()) == {a: 5 for a in SHALLOW}


def test_every_archetype_has_at_least_three_blocking_classes(conn):
    """A denominator with no blocking classes cannot gate a verdict."""
    with conn.cursor() as cur:
        cur.execute("select archetype, count(*) from assumption_classes "
                    "where crit_weight = 1.0 group by archetype")
        for archetype, n in cur.fetchall():
            assert n >= 3, f"{archetype} has only {n} blocking classes"


def test_class_keys_are_archetype_prefixed(conn):
    """Prefixing makes the coverage join unambiguous and keys self-documenting."""
    prefix = {"marketplace": "marketplace", "subscription_saas": "saas", "d2c": "d2c",
              "services": "services", "ad_consumer": "ad", "hardware": "hardware"}
    with conn.cursor() as cur:
        cur.execute("select key, archetype from assumption_classes")
        for key, archetype in cur.fetchall():
            assert key.startswith(prefix[archetype] + "."), key


def test_questions_are_questions(conn):
    with conn.cursor() as cur:
        cur.execute("select key, question from assumption_classes")
        for key, question in cur.fetchall():
            assert question.endswith("?"), key
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/test_seed_integrity.py -v
```
Expected: FAIL — table is empty.

- [ ] **Step 3: Write the seed**

`db/seed/001_assumption_classes.sql`. Marketplace and SaaS are transcribed verbatim from PRD §12.3; the other four are authored to the same standard.

```sql
-- P4: the coverage denominator. Hand-authored static reference data.
-- NEVER generate these rows at runtime (PRD §25).
-- crit_weight: 1.0 = blocking, 0.6 = high, 0.3 = medium.

insert into assumption_classes (key, archetype, label, question, crit_weight) values
-- ── marketplace (PRD §12.3, verbatim) ──────────────────────────────────────
('marketplace.demand_exists',        'marketplace','Demand exists',        'Do buyers actively look for this today?',1.0),
('marketplace.supply_liquidity',     'marketplace','Supply liquidity',     'Will enough supply join and stay?',1.0),
('marketplace.take_rate_tolerance',  'marketplace','Take-rate tolerance',  'Will either side accept the commission?',1.0),
('marketplace.unit_economics',       'marketplace','Unit economics',       'Does revenue per transaction exceed delivered cost?',1.0),
('marketplace.regulatory',           'marketplace','Regulatory',           'Any licence, tax, or compliance requirement?',1.0),
('marketplace.channel_cost',         'marketplace','Channel cost',         'Can both sides be acquired affordably?',0.6),
('marketplace.frequency',            'marketplace','Frequency',            'Is purchase frequency high enough to matter?',0.6),
('marketplace.disintermediation',    'marketplace','Disintermediation',    'What stops both sides transacting off-platform?',0.6),
('marketplace.ops_feasibility',      'marketplace','Ops feasibility',      'Can fulfilment, trust and dispute be operated at this scale?',0.6),
('marketplace.incumbency',           'marketplace','Incumbency',           'Is the space already served or already a graveyard?',0.3),

-- ── subscription_saas (PRD §12.3, verbatim) ────────────────────────────────
('saas.pain_severity',   'subscription_saas','Pain severity',   'Is the pain acute enough to pay for?',1.0),
('saas.wtp_above_cost',  'subscription_saas','WTP above cost',  'Does willingness to pay exceed delivered cost per account?',1.0),
('saas.retention',       'subscription_saas','Retention',       'Will accounts stay long enough to repay acquisition?',1.0),
('saas.channel_cost',    'subscription_saas','Channel cost',    'Is CAC recoverable within an acceptable payback?',1.0),
('saas.buyer_identity',  'subscription_saas','Buyer identity',  'Is there a budget holder who can actually buy?',0.6),
('saas.switching_cost',  'subscription_saas','Switching cost',  'What makes them leave the current solution?',0.6),
('saas.dependency_risk', 'subscription_saas','Dependency risk', 'Do required third parties permit this at viable cost?',0.6),
('saas.data_compliance', 'subscription_saas','Data compliance', 'Any data, privacy or regulatory constraint?',0.6),
('saas.incumbency',      'subscription_saas','Incumbency',      'Is the category already won or already a graveyard?',0.3),
('saas.expansion',       'subscription_saas','Expansion',       'Is there an observable adjacency for expansion?',0.3),

-- ── d2c ────────────────────────────────────────────────────────────────────
('d2c.demand_exists',    'd2c','Demand exists',    'Do people already buy this category online?',1.0),
('d2c.gross_margin',     'd2c','Gross margin',     'Does landed price exceed COGS plus fulfilment by enough to fund acquisition?',1.0),
('d2c.cac_payback',      'd2c','CAC payback',      'Can a first order be acquired below contribution margin?',1.0),
('d2c.repeat_rate',      'd2c','Repeat rate',      'Will enough customers order again to make LTV exceed CAC?',1.0),
('d2c.supply_chain',     'd2c','Supply chain',     'Can the product be sourced at the assumed cost and lead time?',1.0),
('d2c.differentiation',  'd2c','Differentiation',  'Is there a reason to buy this over an incumbent brand?',0.6),
('d2c.return_rate',      'd2c','Return rate',      'Will returns and refunds stay below the margin line?',0.6),
('d2c.channel_access',   'd2c','Channel access',   'Is the assumed acquisition channel open and affordable?',0.6),
('d2c.compliance',       'd2c','Compliance',       'Any labelling, safety, import or category restriction?',0.6),
('d2c.incumbency',       'd2c','Incumbency',       'Is the shelf already crowded with near-identical products?',0.3),

-- ── services (minimum viable, 5) ───────────────────────────────────────────
('services.demand_exists',  'services','Demand exists',  'Are clients already paying someone for this work?',1.0),
('services.rate_tolerance', 'services','Rate tolerance', 'Will clients pay a rate above fully-loaded delivery cost?',1.0),
('services.utilisation',    'services','Utilisation',    'Can billable utilisation stay high enough to be profitable?',1.0),
('services.deliverability', 'services','Deliverability', 'Can the work be delivered at the promised quality and speed?',0.6),
('services.pipeline',       'services','Pipeline',       'Is there a repeatable channel to new clients?',0.6),

-- ── ad_consumer (minimum viable, 5) ────────────────────────────────────────
('ad.audience_reachable', 'ad_consumer','Audience reachable','Can a large enough audience be reached at low cost?',1.0),
('ad.engagement_depth',   'ad_consumer','Engagement depth',  'Will users return often enough to generate inventory?',1.0),
('ad.rpm_vs_cost',        'ad_consumer','RPM vs cost',       'Does revenue per thousand impressions exceed serving and content cost?',1.0),
('ad.retention',          'ad_consumer','Retention',         'Do users stay long enough to repay acquisition?',0.6),
('ad.platform_risk',      'ad_consumer','Platform risk',     'Does the distribution platform permit this and control the terms?',0.6),

-- ── hardware (minimum viable, 5) ───────────────────────────────────────────
('hardware.demand_exists', 'hardware','Demand exists', 'Do buyers pay for a physical device that solves this?',1.0),
('hardware.bom_margin',    'hardware','BOM margin',    'Does the sellable price exceed bill of materials plus assembly and freight?',1.0),
('hardware.manufacturing', 'hardware','Manufacturing', 'Can this be manufactured at the assumed cost, quality and volume?',1.0),
('hardware.certification', 'hardware','Certification', 'Which safety, radio or import certifications are required?',1.0),
('hardware.support_cost',  'hardware','Support cost',  'Will warranty, returns and support stay below the margin line?',0.6);
```

- [ ] **Step 4: Apply the seed and run the tests**

Register the seed in `supabase/config.toml` under `[db.seed]` so `db reset` applies it:
```toml
[db.seed]
enabled = true
sql_paths = ["../db/seed/001_assumption_classes.sql", "../db/seed/002_domain_tiers.sql"]
```

```bash
npx --yes supabase@latest db reset
cd apps/api && uv run pytest tests/test_seed_integrity.py -v
```
Expected: all 6 PASS. 45 rows total.

- [ ] **Step 5: Commit**

```bash
git add db/seed/001_assumption_classes.sql supabase/config.toml apps/api/tests/test_seed_integrity.py
git commit -m "feat(db): hand-seed 45 assumption classes across six archetypes"
```

---

### Task 0.5: Domain → tier map seed

**Files:**
- Create: `db/seed/002_domain_tiers.sql`

**Interfaces:**
- Produces: table `domain_tiers (domain text primary key, tier int, note text)`, consumed by Phase 3's `retrieval/tiers.py`

**Why a table and not a Python dict:** PRD §16.2 says the map is "seeded by hand and extended as needed". A table is extensible without a redeploy, and tier assignment stays auditable — a reviewer can ask why a given URL got tier 1 and read the row.

- [ ] **Step 1: Add the table to `0001_schema.sql`**

Append:
```sql
-- Domain → tier map for rule-based tier assignment (PRD §16.2).
create table domain_tiers (
  domain text primary key,
  tier   int not null check (tier between 1 and 4),
  note   text
);
alter table domain_tiers enable row level security;
create policy "domain_tiers readable by all" on domain_tiers for select using (true);
```
Table count becomes 17; Task 0.2 Step 3 already expects that.

- [ ] **Step 2: Write `db/seed/002_domain_tiers.sql`**

```sql
-- Tier assignment is by rule, not by model (PRD §16.2).
-- Unknown domains default to tier 3 in code.
insert into domain_tiers (domain, tier, note) values
-- tier 1 — regulators, registers, filings, stores, archives
('sec.gov',1,'filings'), ('rbi.org.in',1,'regulator'), ('mca.gov.in',1,'company register'),
('gst.gov.in',1,'tax register'), ('eur-lex.europa.eu',1,'regulator'),
('gov.uk',1,'regulator'), ('ftc.gov',1,'regulator'), ('fda.gov',1,'regulator'),
('web.archive.org',1,'wayback snapshot'), ('play.google.com',1,'store listing'),
('apps.apple.com',1,'store listing'),
-- tier 2 — structured third-party data and official statistics
('crunchbase.com',2,'funding database'), ('tracxn.com',2,'funding database'),
('data.worldbank.org',2,'official statistics'), ('census.gov',2,'official statistics'),
('statista.com',2,'aggregated statistics'), ('g2.com',2,'review aggregate with counts'),
('capterra.com',2,'review aggregate with counts'), ('trustpilot.com',2,'review aggregate'),
-- tier 3 — journalism, analysts, company blogs
('techcrunch.com',3,'journalism'), ('theinformation.com',3,'journalism'),
('economictimes.indiatimes.com',3,'journalism'), ('yourstory.com',3,'journalism'),
('inc42.com',3,'journalism'), ('a16z.com',3,'analyst'), ('failory.com',3,'postmortem collection'),
('autopsy.io',3,'postmortem collection'),
-- tier 4 — community anecdote
('reddit.com',4,'forum'), ('news.ycombinator.com',4,'forum'),
('indiehackers.com',4,'forum'), ('producthunt.com',4,'launch listing'),
('quora.com',4,'forum'), ('stackoverflow.com',4,'forum');
```

- [ ] **Step 3: Verify**

```bash
npx --yes supabase@latest db reset
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -c "select tier, count(*) from domain_tiers group by tier order by tier"
```
Expected: rows for tiers 1–4, none for tier 5.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/0001_schema.sql db/seed/002_domain_tiers.sql
git commit -m "feat(db): seed domain to source-tier map"
```

---

### Task 0.6: Pydantic contracts

**Files:**
- Create: `apps/api/jury/schemas/__init__.py`, `enums.py`, `scope.py`, `claim.py`, `assumption.py`, `economics.py`, `experiment.py`, `verdict.py`
- Create: `apps/api/jury/settings.py`
- Test: `apps/api/tests/test_schema_contracts.py`

**Interfaces:**
- Consumes: nothing internal — `schemas/` imports no other Jury module (spec §6)
- Produces:
  - `Scope(geo: Geo, segment: Segment, tier: Tier | None, period: str | None)`
  - `ClaimRecord` with fields exactly as PRD §6.1
  - `Settings` with every external key `str | None = None`
  - `CriterionSpec(metric: str, comparator: Comparator, threshold: float, n: int | None)`
  - `ConfidenceComponents(coverage, mean_strength, contradiction, open_critical: float)`

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_schema_contracts.py`:
```python
import pytest
from pydantic import ValidationError

from jury.schemas.claim import ClaimRecord
from jury.schemas.enums import Chair, Direction, Geo, Segment
from jury.schemas.experiment import CriterionSpec
from jury.schemas.scope import Scope

VALID = {
    "assumption_id": None,
    "new_assumption": {"statement": "SMBs in India pay above 149 INR per month for this.",
                       "class_key": "saas.wtp_above_cost"},
    "direction": "supports",
    "variable": "price_monthly",
    "value_num": 149.0,
    "unit": "INR_per_month",
    "scope": {"geo": "IN", "segment": "smb", "tier": "entry", "period": "2026"},
    "confidence": 0.8,
    "source_url": "https://example.test/pricing",
    "source_tier": 1,
    "excerpt": "Starter plan is priced at 149 INR per month.",
    "chair": "market",
}


def test_valid_claim_parses():
    c = ClaimRecord.model_validate(VALID)
    assert c.chair is Chair.MARKET
    assert c.direction is Direction.SUPPORTS
    assert c.scope.geo is Geo.IN


def test_tier_five_claim_is_rejected():
    """P1: a model prior is not evidence and must not survive parsing."""
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"source_tier": 5})


def test_excerpt_over_240_chars_rejected():
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"excerpt": "x" * 241})


def test_non_http_source_url_rejected():
    """SSRF surface: target URLs are partly model-selected (PRD §17.4)."""
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"source_url": "file:///etc/passwd"})


def test_claim_needs_either_assumption_id_or_new_assumption():
    bad = dict(VALID)
    bad["new_assumption"] = None
    bad["assumption_id"] = None
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(bad)


def test_value_range_must_be_ordered():
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(VALID | {"value_min": 100.0, "value_max": 50.0})


def test_free_text_scope_is_rejected():
    """PRD §12.1: a free-text scope is uncomparable and would break the conflict engine."""
    with pytest.raises(ValidationError):
        Scope.model_validate({"geo": "India", "segment": "smb"})


def test_criterion_spec_requires_machine_evaluable_comparator():
    spec = CriterionSpec.model_validate(
        {"metric": "prepay_count", "comparator": ">=", "threshold": 4, "n": 20})
    assert spec.threshold == 4
    with pytest.raises(ValidationError):
        CriterionSpec.model_validate(
            {"metric": "vibes", "comparator": "feels better", "threshold": 4})


def test_settings_tolerate_a_completely_empty_env(monkeypatch):
    """Spec §3: the build must be verifiable before any credential exists."""
    for k in ("GROQ_API_KEY", "BRAVE_API_KEY", "SUPABASE_SERVICE_ROLE_KEY",
              "UPSTASH_REDIS_REST_URL", "EXA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from jury.settings import Settings
    s = Settings()
    assert s.groq_api_key is None
    assert s.offline is True          # defaults to offline when unkeyed
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/test_schema_contracts.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jury.schemas'`.

- [ ] **Step 3: Write `jury/schemas/enums.py`**

```python
"""Closed sets. Every one of these is a hard constraint from PRD §12.2 / §6.1.

Free text where an enum belongs is the failure mode PRD §12.1 warns about:
"a free-text scope is uncomparable, and the conflict engine would flag
Rs 149 US-SMB against Rs 500 IN-enterprise as a contradiction."
"""
from enum import StrEnum


class Archetype(StrEnum):
    MARKETPLACE = "marketplace"
    SUBSCRIPTION_SAAS = "subscription_saas"
    D2C = "d2c"
    SERVICES = "services"
    AD_CONSUMER = "ad_consumer"
    HARDWARE = "hardware"


class Chair(StrEnum):
    MARKET = "market"
    CUSTOMER = "customer"
    PRECEDENT = "precedent"
    DEPENDENCIES = "dependencies"
    ECONOMICS = "economics"


class Direction(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"


class Geo(StrEnum):
    IN = "IN"; US = "US"; EU = "EU"; UK = "UK"
    SEA = "SEA"; MENA = "MENA"; LATAM = "LATAM"; GLOBAL = "GLOBAL"


class Segment(StrEnum):
    CONSUMER = "consumer"; PROSUMER = "prosumer"; SMB = "smb"
    MID_MARKET = "mid_market"; ENTERPRISE = "enterprise"; PUBLIC_SECTOR = "public_sector"


class Tier(StrEnum):
    FREE = "free"; ENTRY = "entry"; MID = "mid"
    PREMIUM = "premium"; ENTERPRISE = "enterprise"


class Criticality(StrEnum):
    BLOCKING = "blocking"; HIGH = "high"; MEDIUM = "medium"; LOW = "low"


class Uncertainty(StrEnum):
    UNKNOWN = "unknown"; UNCERTAIN = "uncertain"
    LIKELY = "likely"; ESTABLISHED = "established"


class Falsifiability(StrEnum):
    TESTABLE_NOW = "testable_now"
    TESTABLE_COSTLY = "testable_costly"
    UNTESTABLE = "untestable"


class AssumptionStatus(StrEnum):
    NO_EVIDENCE = "no_evidence"; UNCERTAIN = "uncertain"
    SUPPORTED = "supported"; REFUTED = "refuted"; CONTESTED = "contested"


class Origin(StrEnum):
    FOUNDER = "founder"; DISCOVERED = "discovered"


class ConflictKind(StrEnum):
    FOUNDER_VS_WORLD = "founder_vs_world"
    CHAIR_VS_CHAIR = "chair_vs_chair"
    NO_EVIDENCE = "no_evidence"
    SCOPE_GAP = "scope_gap"


class ConflictRule(StrEnum):
    R1 = "R1"; R2 = "R2"; R3 = "R3"; R4 = "R4"; R5 = "R5"


class ConflictStatus(StrEnum):
    OPEN = "open"; RESOLVED = "resolved"
    CONCEDED = "conceded"; UNRESOLVABLE = "unresolvable"


class Provenance(StrEnum):
    EVIDENCE_BACKED = "evidence_backed"
    FOUNDER_ASSERTED = "founder_asserted"


class Decision(StrEnum):
    PROCEED = "PROCEED"; PIVOT = "PIVOT"; STOP = "STOP"; HUNG_JURY = "HUNG_JURY"


class ExperimentMethod(StrEnum):
    FAKE_DOOR = "fake_door"; PRESALE = "presale"
    INTERVIEW_SCRIPT = "interview_script"; SUPPLIER_QUOTE = "supplier_quote"
    LANDING_CTR = "landing_ctr"; REGISTRY_CHECK = "registry_check"
    DOCUMENTED_PROXY = "documented_proxy"   # spec §26.6: retention is not testable in 30 days


class Comparator(StrEnum):
    GTE = ">="; GT = ">"; LTE = "<="; LT = "<"; EQ = "=="
```

- [ ] **Step 4: Write `jury/schemas/scope.py`**

```python
from pydantic import BaseModel, ConfigDict, field_validator

from jury.schemas.enums import Geo, Segment, Tier

_PERIOD = __import__("re").compile(r"^\d{4}(-Q[1-4])?$")


class Scope(BaseModel):
    """Typed applicability of a claim (PRD §12.2). Enumerated so overlap is computable."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    geo: Geo
    segment: Segment
    tier: Tier | None = None
    period: str | None = None

    @field_validator("period")
    @classmethod
    def _period_shape(cls, v: str | None) -> str | None:
        if v is not None and not _PERIOD.match(v):
            raise ValueError("period must be YYYY or YYYY-Qn")
        return v
```

- [ ] **Step 5: Write `jury/schemas/claim.py`**

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jury.schemas.enums import Chair, Direction
from jury.schemas.scope import Scope


class NewAssumption(BaseModel):
    """How a chair introduces an assumption the extractor missed (PRD §7.3)."""
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=10, max_length=300)
    class_key: str


class ClaimRecord(BaseModel):
    """The output contract for all five chairs. PRD §6.1, field-for-field.

    Every chair emits only typed claim records. No prose commentary is persisted
    or displayed except cross-examination transcripts.
    """
    model_config = ConfigDict(extra="forbid")

    assumption_id: str | None = None
    new_assumption: NewAssumption | None = None
    direction: Direction
    variable: str | None = None
    value_num: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    unit: str | None = None
    scope: Scope
    confidence: float = Field(ge=0.0, le=1.0)
    source_url: str = Field(pattern=r"^https?://")
    source_tier: int = Field(ge=1, le=4)   # P1: tier 5 is not evidence
    excerpt: str = Field(min_length=1, max_length=240)
    chair: Chair

    @model_validator(mode="after")
    def _must_attach_to_an_assumption(self) -> "ClaimRecord":
        if self.assumption_id is None and self.new_assumption is None:
            raise ValueError("claim must reference assumption_id or supply new_assumption")
        return self

    @model_validator(mode="after")
    def _range_ordered(self) -> "ClaimRecord":
        if (self.value_min is not None and self.value_max is not None
                and self.value_min > self.value_max):
            raise ValueError("value_min must not exceed value_max")
        return self
```

- [ ] **Step 6: Write the remaining schema modules**

`jury/schemas/experiment.py`:
```python
from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import Comparator, ExperimentMethod


class CriterionSpec(BaseModel):
    """P9: machine-evaluable kill criterion, pre-registered before the test runs.

    PRD §16.6: pre-registering the threshold is what stops the founder returning
    with an ambiguous result and rationalising it.
    """
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(min_length=1)
    comparator: Comparator
    threshold: float
    n: int | None = Field(default=None, ge=1)


class ExperimentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumption_id: str
    target_variable: str | None
    method: ExperimentMethod
    instructions: str = Field(min_length=20)
    kill_criterion: str = Field(min_length=10)   # P9, non-null
    criterion_spec: CriterionSpec
    est_cost: float | None = None
    est_days: int | None = None
    priority: int = Field(ge=1)
    limitation: str | None = None                # spec §26.6, retention proxy
```

`jury/schemas/economics.py`:
```python
from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import Provenance


class Parameter(BaseModel):
    """PRD §16.5: every parameter carries provenance, which is what lets
    sensitivity mechanically nominate the next experiment (PRD §16.6)."""
    model_config = ConfigDict(extra="forbid")
    value: float
    unit: str
    provenance: Provenance
    source_id: str | None = None
    assumption_id: str | None = None


class Breakpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable: str
    threshold: float
    direction: str = Field(pattern="^(above|below)$")
    unit: str
    output: str
    sentence: str


class SensitivityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable: str
    elasticity: float
    provenance: Provenance


class ModelOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contribution_margin: float
    ltv: float
    ltv_cac: float
    payback_months: float | None
    breakeven_volume_monthly: float | None
```

`jury/schemas/verdict.py`:
```python
from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import Decision


class ConfidenceComponents(BaseModel):
    """PRD §9.3: the UI always displays the four components alongside the total.
    A number with a visible decomposition is defensible; one without is not."""
    model_config = ConfigDict(extra="forbid")
    coverage: float = Field(ge=0.0, le=1.0)
    mean_strength: float = Field(ge=0.0, le=1.0)
    contradiction: float = Field(ge=0.0)
    open_critical: float = Field(ge=0.0, le=1.0)


class VerdictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Decision
    evidence_confidence: float = Field(ge=0.0, le=100.0)
    components: ConfidenceComponents
    gate_triggered: str | None
    friction: list[dict]
    rationale: str
```

`jury/schemas/assumption.py`:
```python
from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import (
    AssumptionStatus, Chair, Criticality, Falsifiability, Origin, Uncertainty,
)


class AssumptionDraft(BaseModel):
    """Output of extraction, input to the hearing. Editable by the founder (F5)."""
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=10, max_length=300)
    class_key: str | None = None
    origin: Origin = Origin.FOUNDER
    discovered_by: Chair | None = None
    criticality: Criticality
    uncertainty: Uncertainty
    falsifiability: Falsifiability
    asserted_variable: str | None = None
    asserted_value: float | None = None
    asserted_unit: str | None = None


class AssumptionRecord(AssumptionDraft):
    id: str
    status: AssumptionStatus = AssumptionStatus.NO_EVIDENCE
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
```

- [ ] **Step 7: Write `jury/settings.py`**

```python
"""Configuration. Every external credential is optional by construction.

Spec §3: the build must be verifiable before any credential exists, so a missing
key is a normal state that selects a fixture transport — never a crash.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                      case_sensitive=False)

    # database
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_url: str | None = Field(default=None, alias="NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key: str | None = Field(default=None, alias="NEXT_PUBLIC_SUPABASE_ANON_KEY")
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None

    # llm
    llm_provider: str = "groq"
    groq_api_key: str | None = None
    llm_model_reasoning: str | None = None
    llm_model_fast: str | None = None
    llm_model_fallback: str | None = None

    # retrieval
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    exa_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    producthunt_token: str | None = None

    # infra
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None

    app_base_url: str = "http://localhost:3000"
    jury_offline: int | None = None

    @property
    def offline(self) -> bool:
        """Explicit JURY_OFFLINE wins; otherwise offline iff no LLM key exists."""
        if self.jury_offline is not None:
            return bool(self.jury_offline)
        return self.groq_api_key is None


settings = Settings()
```

- [ ] **Step 8: Run the tests**

```bash
cd apps/api && uv run pytest tests/test_schema_contracts.py -v
```
Expected: all 10 PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/api/jury apps/api/tests/test_schema_contracts.py
git commit -m "feat(schemas): typed contracts for claims, scope, economics, experiments, verdict"
```

---

### Task 0.7: Phase gate and changelog

- [ ] **Step 1: Run the full suite**

```bash
cd apps/api && uv run pytest -q
```
Expected: 22 passed (6 db constraints + 6 seed integrity + 10 schema contracts).

- [ ] **Step 2: Append the real output to `CHANGELOG.md`**

Replace the `_in progress_` line with what actually happened: files added, the gate command, its verbatim output, and the `superseded_by` direction deviation from Task 0.3 Step 4.

- [ ] **Step 3: Commit and push**

```bash
git add -A
git commit -m "docs: phase 0 changelog entry with gate output"
git branch -M main && git push -u origin main
```

---

## Phase 0 exit criteria

- [ ] 16 tables exist with enum and range constraints
- [ ] RLS enabled on every table; child tables authorise through `projects`
- [ ] **Postgres itself** rejects `UPDATE`/`DELETE` on `evidence_items`, service role included
- [ ] `unique (project_id, dedup_hash)` rejects a duplicate source
- [ ] Tier-5 and non-2xx sources rejected by CHECK constraint
- [ ] 45 assumption classes seeded; every archetype has ≥3 blocking classes
- [ ] `Settings()` constructs against a completely empty environment
- [ ] `uv run pytest -q` green
- [ ] `CHANGELOG.md` records the gate output and the one deviation
