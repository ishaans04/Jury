-- RLS per PRD §14.4. Every user-owned table authorises through its project.
-- (domain_tiers was already enabled + policied in 0001_schema.sql.)
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
-- evidence_items is deliberately excluded here: 0003_immutability.sql gives it
-- its own insert/select-only policies, and a blanket "for all" policy from this
-- loop would contradict that (it would let RLS itself imply update/delete are
-- policy-governed, when the intent is that no update/delete path exists at all).
do $$
declare t text;
begin
  foreach t in array array['runs','pitches','assumptions','conflicts',
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
