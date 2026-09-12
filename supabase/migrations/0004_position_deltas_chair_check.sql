-- Chairs are a closed set. Sibling chair columns already constrain this;
-- position_deltas.chair was missed in the original schema.
alter table position_deltas
  add constraint position_deltas_chair_check
  check (chair in ('market','customer','precedent','dependencies','economics'));
