-- Persist which chairs degraded (budget exhaustion) so a client reading the run
-- row can show the boardroom's `partial` badge for the silent-budget path, not
-- only for chair errors. The verdict already accounts for degradation through
-- coverage; this column only surfaces it. Purely additive, no privilege/RLS
-- change -- runs' existing RLS already scopes reads to the owning project.
alter table runs
  add column partial_chairs jsonb not null default '[]'::jsonb;
