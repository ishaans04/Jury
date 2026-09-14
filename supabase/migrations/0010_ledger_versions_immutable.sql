-- P6 extended to ledger_versions (Phase 6 batch V controller ruling): a
-- stored snapshot/diff pair is a historical fact, exactly like an
-- evidence_items row. `unique (project_id, version)` (0001_schema.sql) stops
-- a duplicate version NUMBER, but does nothing to stop an UPDATE rewriting an
-- existing version's snapshot or diff in place, and nothing to stop a
-- TRUNCATE wiping the whole ledger history. Same two-layer treatment
-- evidence_items got (0003_immutability.sql, 0005_evidence_no_truncate.sql),
-- applied here in one migration since 0007/0008/0009 already mapped the
-- FK-cascade traps this same pattern hits, instead of rediscovering them the
-- hard way across several follow-up fixes.
--
--   1. REVOKE stops anon/authenticated/service_role, the roles the app
--      actually connects as, plus `postgres` (this stack's table owner and
--      the role every migration/test runs as -- NOT a genuine superuser,
--      see tests/test_db_constraints.py's ADMIN_DATABASE_URL comment).
--   2. BEFORE UPDATE / BEFORE TRUNCATE triggers that raise unconditionally,
--      for every role including a genuine superuser (`supabase_admin`),
--      which bypasses the REVOKE entirely -- the trigger, not the REVOKE, is
--      what actually holds P6 against that role.
--
-- DELETE is handled differently, deliberately mirroring
-- 0007_evidence_delete_via_cascade.sql's ruling: erasing an entire project
-- (or account) at its owner's explicit request is not "falsifying the
-- ledger in place" -- nothing is misrepresented, the record ceases to exist
-- because its owner asked for that, which is exactly what `ON DELETE
-- CASCADE` is for. So DELETE is revoked from anon/authenticated/
-- service_role only (no application code path can ever issue a bare DELETE
-- against ledger_versions) and left granted to the table owner, with no
-- BEFORE DELETE trigger -- a trigger there would block the very
-- project-erasure cascade this carve-out exists to allow.
revoke update, truncate on ledger_versions from anon, authenticated, service_role, postgres;
revoke delete on ledger_versions from anon, authenticated, service_role;

create or replace function jury_ledger_versions_is_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'ledger_versions is insert-only; a version is a historical '
                  'snapshot, never corrected or replaced in place';
end $$;

create trigger ledger_versions_no_update before update on ledger_versions
  for each row execute function jury_ledger_versions_is_immutable();
create trigger ledger_versions_no_truncate before truncate on ledger_versions
  for each statement execute function jury_ledger_versions_is_immutable();

-- FK cascade check, done up front rather than found the hard way across two
-- more migrations (0008/0009's own lesson, applied here instead of relearned):
-- `ledger_versions.run_id` was `references runs(id)` with the implicit
-- default action, NO ACTION. Deleting a project cascades to delete its runs
-- (runs.project_id on delete cascade) and, separately, to delete its
-- ledger_versions (ledger_versions.project_id on delete cascade, already in
-- 0001_schema.sql) -- but Postgres still independently verifies, for the
-- run_id foreign key, that no ledger_versions row is left pointing at a runs
-- row about to disappear. A NO ACTION fk's existence check takes a
-- `SELECT ... FOR KEY SHARE` lock on the REFERENCING table (ledger_versions
-- here), which requires UPDATE privilege on it -- revoked from every role,
-- including postgres, immediately above. Left as NO ACTION, this migration
-- would make every project (and run) delete fail with "permission denied for
-- table ledger_versions", exactly the failure class 0008_evidence_fk_cascades.sql
-- fixed for evidence_items. Fixed the same way: ON DELETE CASCADE satisfies
-- the FK via an actual delete (needs DELETE privilege -- still granted to the
-- owner above) instead of a lock-and-check (needs UPDATE privilege -- revoked).
alter table ledger_versions
  drop constraint ledger_versions_run_id_fkey,
  add constraint ledger_versions_run_id_fkey
    foreign key (run_id) references runs(id) on delete cascade;

-- Note for the next reader: no other table anywhere in 0001_schema.sql
-- references ledger_versions (checked: `grep -n "references ledger_versions"`
-- across every migration returns nothing), so there is no inbound FK to this
-- table that could hit the same lock-privilege trap from the other
-- direction -- unlike evidence_items, which needed 0009 for exactly that.
