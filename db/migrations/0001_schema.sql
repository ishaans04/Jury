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

-- Domain → tier map for rule-based tier assignment (PRD §16.2).
create table domain_tiers (
  domain text primary key,
  tier   int not null check (tier between 1 and 4),
  note   text
);
alter table domain_tiers enable row level security;
create policy "domain_tiers readable by all" on domain_tiers for select using (true);
