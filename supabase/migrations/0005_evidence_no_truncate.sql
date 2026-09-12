-- Fix round 1: TRUNCATE was not covered by 0003_immutability.sql.
--
-- TRUNCATE bypasses RLS entirely (FORCE ROW LEVEL SECURITY does not apply to
-- it) and fires no row-level trigger, so the BEFORE UPDATE/DELETE triggers in
-- 0003_immutability.sql never see it. Without this migration, service_role
-- (and anon/authenticated/postgres) could run `truncate evidence_items
-- cascade` and wipe the entire evidence ledger in one statement -- verified
-- empirically before this fix: the same REVOKE/trigger split that closes
-- UPDATE and DELETE does nothing for TRUNCATE, which is a distinct grantable
-- privilege and a distinct trigger event in Postgres.
--
-- Same two-layer pattern as 0003_immutability.sql, extended to TRUNCATE:
--   1. REVOKE stops anon/authenticated/service_role/postgres.
--   2. A statement-level trigger (row-level triggers are rejected by Postgres
--      for TRUNCATE) stops a genuine superuser, which bypasses the REVOKE.
revoke truncate on evidence_items from anon, authenticated, service_role, postgres;

create trigger evidence_no_truncate before truncate on evidence_items
  for each statement execute function jury_evidence_is_immutable();
