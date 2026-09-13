-- Fix round 2 (batch M audit): sources had no INSERT policy at all.
--
-- sources is deliberately global and shared: a fetched pricing page is not
-- private data, and a shared cache reduces search-quota burn (PRD §14.4).
-- Phase 0 (0002_rls.sql) gave it only a SELECT policy, which -- with RLS
-- enabled and no policy granting INSERT -- silently blocked every write on
-- the real path. Tests never caught this because the local test connection
-- runs as `postgres`, which owns the table; `sources` was never given
-- `FORCE ROW LEVEL SECURITY` (unlike `evidence_items`), so the owner
-- bypasses RLS entirely and every repository test looked green while the
-- production write path -- which runs as `authenticated`, not as the owner
-- -- could not write a source row at all. Verified empirically before this
-- fix (see batch-M-report.md): `insert into sources (...)` as `authenticated`
-- raised `InsufficientPrivilege: new row violates row-level security policy
-- for table "sources"`.
--
-- Any authenticated user may contribute a source row: nothing
-- user-identifying is stored on it, and a second insert of the same URL is
-- idempotent via the table's own `unique (canonical_url)` constraint.
create policy "sources insertable by authenticated" on sources
  for insert with check (auth.role() = 'authenticated');

-- Deliberately NO update or delete policy. sources is a globally shared,
-- deduplicated table -- an UPDATE grant would let any authenticated user
-- rewrite another user's cached source metadata (retrieved_at, tier, title,
-- http_status), which is a quiet integrity hole on data nobody individually
-- owns. SourceRepo.upsert (jury/db/repositories.py) is idempotent on
-- canonical_url via `on conflict (canonical_url) do nothing` followed by a
-- select of the existing row's id, so it needs no UPDATE grant to behave
-- correctly.
