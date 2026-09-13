-- Fix round 4 (batch-N audit, continued): 0007_evidence_delete_via_cascade.sql
-- restored DELETE on evidence_items to its owner and dropped the row trigger
-- that blocked it, but a project delete still failed afterwards with
-- "permission denied for table evidence_items".
--
-- Root cause: deleting a row that OTHER rows reference with a plain (NO
-- ACTION) foreign key requires Postgres to take a `SELECT ... FOR KEY SHARE`
-- lock on each of those referencing tables, to confirm nothing still points
-- at the row being removed. That lock requires UPDATE privilege on the
-- referencing table -- and evidence_items itself is one of the tables with
-- an inbound NO ACTION reference, twice over, plus a third one from
-- position_deltas:
--
--   evidence_items_run_id_fkey            evidence_items.run_id  -> runs
--   evidence_items_superseded_by_fkey     evidence_items.superseded_by
--                                            -> evidence_items (self)
--   position_deltas_new_evidence_id_fkey  position_deltas.new_evidence_id
--                                            -> evidence_items
--
-- UPDATE on evidence_items is the one privilege P6 must never grant to
-- anyone (0003_immutability.sql), so none of these three can be left as
-- plain NO ACTION: the FK-existence check for a run/evidence/position_delta
-- delete would need exactly the UPDATE lock P6 permanently withholds.
--
-- Each of these three is also semantically correct as CASCADE on its own
-- merits, independent of the privilege mechanics above:
--   - run_id: evidence cannot outlive the run that produced it. Every other
--     evidence_items FK to a container row (project_id, assumption_id)
--     already cascades; run_id not cascading reads as an oversight in the
--     original schema, not a deliberate decision.
--   - superseded_by: a superseding row (the P6-compliant way to correct
--     evidence, per 0003_immutability.sql's own comment) cannot meaningfully
--     outlive the row it supersedes.
--   - position_deltas.new_evidence_id: a recorded position change citing
--     evidence that no longer exists is meaningless, not a fact worth
--     preserving.
--
-- Deliberately NOT touched: evidence_items_source_id_fkey (evidence_items.
-- source_id -> sources), which stays NO ACTION. `sources` is a shared,
-- globally-deduplicated, append-only cache holding nothing user-identifying
-- (PRD §14.4) -- there is nothing about it that erasure needs to reach, and
-- a source row that outlives the evidence citing it is the correct, intended
-- shape (a fetched pricing page some other project may still want). A
-- source therefore remains permanently undeletable so long as ANY evidence
-- row anywhere cites it -- which is a feature of the shared-cache design,
-- not a gap to close.
alter table evidence_items
  drop constraint evidence_items_run_id_fkey,
  add constraint evidence_items_run_id_fkey
    foreign key (run_id) references runs(id) on delete cascade;

alter table evidence_items
  drop constraint evidence_items_superseded_by_fkey,
  add constraint evidence_items_superseded_by_fkey
    foreign key (superseded_by) references evidence_items(id) on delete cascade;

alter table position_deltas
  drop constraint position_deltas_new_evidence_id_fkey,
  add constraint position_deltas_new_evidence_id_fkey
    foreign key (new_evidence_id) references evidence_items(id) on delete cascade;
