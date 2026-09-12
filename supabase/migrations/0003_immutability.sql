-- P6: evidence is immutable. Corrections happen by superseding, never by updating.
-- PRD §14.4: "evidence_items additionally denies UPDATE and DELETE to all roles
-- including the service role, enforcing P6 at the database level rather than in
-- application code."
--
-- Two enforcement layers, doing two different jobs:
--   1. REVOKE stops anon/authenticated/service_role, the roles the app actually
--      connects as.
--   2. The BEFORE UPDATE/DELETE triggers stop everyone, including a role that
--      owns the table or otherwise bypasses grants (e.g. the local `postgres`
--      role used by tests and migrations) -- a REVOKE has no effect on such a
--      role, so it is not a substitute for the trigger, only a belt-and-braces
--      addition alongside it. The trigger is the guarantee that actually holds
--      against every possible caller.
revoke update, delete on evidence_items from anon, authenticated, service_role, postgres;

alter table evidence_items force row level security;   -- applies RLS to the table owner

create policy "evidence insert own" on evidence_items for insert with check (
  exists (select 1 from projects p where p.id = evidence_items.project_id
          and p.user_id = auth.uid())
);
create policy "evidence select own" on evidence_items for select using (
  exists (select 1 from projects p where p.id = evidence_items.project_id
          and p.user_id = auth.uid())
);
-- Deliberately NO update or delete policy exists. Combined with the REVOKE above
-- and the triggers below, there is no path -- policy, grant, or role -- to mutate
-- or remove a row.

-- Belt and braces: a trigger that raises even if a future migration re-grants,
-- and that fires regardless of who owns the table or which grants they hold.
create or replace function jury_evidence_is_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'evidence_items is insert-only (P6); correct by inserting a '
                  'superseding row and setting superseded_by';
end $$;

create trigger evidence_no_update before update on evidence_items
  for each row execute function jury_evidence_is_immutable();
create trigger evidence_no_delete before delete on evidence_items
  for each row execute function jury_evidence_is_immutable();

-- NOTE on superseded_by's direction (evidence_items and, by the same reasoning,
-- assumptions): an insert-only table cannot write a column on the row being
-- corrected, because that would be an UPDATE of an existing row. So
-- superseded_by is set on the *new* row and points *backwards* at the row it
-- replaces, not forwards from the old row to its replacement as the column name
-- might suggest. "Current" evidence/assumptions are therefore the rows that are
-- NOT referenced by any other row's superseded_by -- i.e.
--   select * from evidence_items e
--   where not exists (
--     select 1 from evidence_items e2 where e2.superseded_by = e.id
--   );
