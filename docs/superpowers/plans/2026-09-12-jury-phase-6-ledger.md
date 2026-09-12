# Phase 6 — The Living Ledger

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **PRD:** §7.10 (return visit), §16.8 (diff engine), §12 (`ledger_versions`), F14, spec §26.5

**Phase goal:** A founder returns weeks later, logs a real experiment result, and the ledger updates **mechanically** against the pre-registered criterion — producing a version diff rendered as one causal sentence.

**Why this is the strongest beat (PRD §16.8):** *"This is the cheapest-to-build and strongest demo beat in the product."* It is the 4:20 mark of the §22 script, and it is the thing that distinguishes a ledger from a report. PRD §2.2: *"Not a report generator. A regenerated report is explicitly a failure mode; the ledger updates and diffs."*

**Gate:** logging `3` against a pre-registered `>=4 of 20` flips the assumption `uncertain → refuted` with **no model involvement**, moves the bound parameter's provenance, moves the breakpoint, recomputes the verdict, and renders the PRD §7.10 sentence.

---

## File structure

| Path | Responsibility |
|---|---|
| `jury/engines/affected.py` | Downstream closure of a changed assumption (spec §26.5) |
| `jury/graph/nodes/version.py` | Snapshot + diff writer |
| `jury/graph/rerun.py` | Affected-only re-run graph |
| `jury/api/routers/experiments.py` | `POST /experiments/{id}/result` |
| `jury/api/routers/versions.py` | `GET /projects/{id}/versions`, `/versions/{v}/diff` |
| `jury/db/snapshot.py` | Build a `Snapshot` from the live ledger |
| `apps/web/components/ledger/{VersionList,CausalDiff,LogResultForm}.tsx` | |
| `apps/web/app/projects/[id]/versions/page.tsx` | |

---

### Task 6.1: Snapshot builder

**Files:** Create `jury/db/snapshot.py`; Test `tests/db/test_snapshot.py`

**Interfaces:**
- `async def build_snapshot(pool, project_id: str, run_id: str) -> dict` — returns the `Snapshot` shape `engines/diff.compute_diff` consumes: `assumptions`, `evidence_counts`, `conflicts`, `parameters`, `breakpoints`, `confidence`, `verdict`

The snapshot must be **complete and self-contained** — `ledger_versions.snapshot` is an immutable record, so a later schema change must not make an old version unreadable.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/db/test_snapshot.py
async def test_the_snapshot_shape_matches_what_compute_diff_consumes(pool, seeded):
    snap = await build_snapshot(pool, project_id, run_id)
    assert set(snap) == {"assumptions", "evidence_counts", "conflicts",
                         "parameters", "breakpoints", "confidence", "verdict"}
    assert compute_diff(None, snap) == []          # must not raise


async def test_evidence_counts_are_nested_by_chair_then_tier(pool, seeded):
    snap = await build_snapshot(pool, project_id, run_id)
    assert snap["evidence_counts"]["market"]["1"] >= 1


async def test_assumptions_carry_statement_status_and_origin(pool, seeded):
    snap = await build_snapshot(pool, project_id, run_id)
    a = next(iter(snap["assumptions"].values()))
    assert {"statement", "status", "origin"} <= set(a)


async def test_the_snapshot_is_json_serialisable(pool, seeded):
    """It is stored in a jsonb column; a Decimal or a UUID would break the write."""
    import json
    json.dumps(await build_snapshot(pool, project_id, run_id))


async def test_the_snapshot_is_self_contained_and_carries_no_foreign_keys_only(pool, seeded):
    """An immutable version must remain readable without joining live tables."""
    snap = await build_snapshot(pool, project_id, run_id)
    a = next(iter(snap["assumptions"].values()))
    assert a["statement"]                          # text, not just an id


async def test_confidence_carries_the_total_and_all_four_components(pool, seeded):
    snap = await build_snapshot(pool, project_id, run_id)
    assert set(snap["confidence"]) == {"total", "coverage", "mean_strength",
                                       "contradiction", "open_critical"}


async def test_two_builds_of_an_unchanged_ledger_are_identical(pool, seeded):
    """Otherwise every version would diff against itself and produce noise."""
    a = await build_snapshot(pool, project_id, run_id)
    b = await build_snapshot(pool, project_id, run_id)
    assert a == b
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** Cast every `numeric` to `float` and every `uuid` to `str` at the boundary so the jsonb write never sees a `Decimal`.
- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(db): self-contained ledger snapshot builder"`

---

### Task 6.2: Version writer

**Files:** Create `jury/graph/nodes/version.py`; Test `tests/graph/test_version.py`

**Interfaces:** `async def write_version(state, *, pool, repos, trace) -> dict` → `{"version": int, "diff": list[dict]}`

`ledger_versions` has `unique (project_id, version)`; versions are dense and start at 1.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_first_run_writes_version_one_with_an_empty_diff(pool, seeded):
    out = await write_version(state, pool=pool, ...)
    assert out["version"] == 1 and out["diff"] == []


async def test_the_second_run_writes_version_two_with_a_computed_diff(pool, seeded):
    await write_version(state_v1, ...)
    out = await write_version(state_v2_changed, ...)
    assert out["version"] == 2 and out["diff"]


async def test_versions_are_dense_and_monotonic(pool, seeded):
    for expected in (1, 2, 3):
        assert (await write_version(state, ...))["version"] == expected


async def test_an_existing_version_is_never_overwritten(pool, seeded):
    """P6's spirit extended to versions: a snapshot is a historical fact."""
    await write_version(state_v1, ...)
    first = await fetch_version(project_id, 1)
    await write_version(state_v2, ...)
    assert await fetch_version(project_id, 1) == first


async def test_ledger_versions_are_immutable_at_the_database_level(pool, seeded):
    """A unique constraint on (project_id, version) stops a duplicate version
    NUMBER; it does nothing to stop an UPDATE that rewrites an existing
    version's snapshot or diff, and nothing to stop TRUNCATE.

    Apply the same three-layer treatment evidence_items received in Phase 0:
      revoke update, delete, truncate on ledger_versions
        from anon, authenticated, service_role, postgres;
      before update / before delete  -> for each row   -> raise
      before truncate                -> for each statement -> raise

    (The truncate trigger is what stops a genuine superuser, which bypasses
    the REVOKE. This gap was found on evidence_items during Phase 0 review;
    it is the same class of bug.)
    """
    await write_version(state_v1, ...)
    for stmt in ("update ledger_versions set diff = '[]'",
                 "delete from ledger_versions",
                 "truncate table ledger_versions"):
        with pytest.raises(psycopg.Error):
            await execute_as(pool, "service_role", stmt)


async def test_the_snapshot_and_the_diff_are_both_persisted(pool, seeded):
    out = await write_version(state_v2, ...)
    row = await fetch_version(project_id, out["version"])
    assert row["snapshot"] and row["diff"] is not None


async def test_a_concurrent_second_writer_does_not_produce_a_duplicate_version(pool, seeded):
    """unique (project_id, version) must be handled, not merely declared."""
    results = await asyncio.gather(write_version(state, ...), write_version(state, ...),
                                   return_exceptions=True)
    versions = [r["version"] for r in results if isinstance(r, dict)]
    assert len(set(versions)) == len(versions)
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** Take the next version inside a transaction with `select coalesce(max(version),0)+1 ... for update` on the project row; on `UniqueViolation`, retry once.
- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(graph): immutable ledger version writer with computed diff"`

---

### Task 6.3: Affected-only closure

**Files:** Create `jury/engines/affected.py`; Test `tests/engines/test_affected.py`

**Interfaces:**
- `def affected_closure(changed_assumption_id: str, *, parameter_bindings: dict[str, str], sensitivity: list[dict]) -> AffectedSet`
- `AffectedSet` dataclass: `assumptions: set[str]`, `parameters: set[str]`, `recompute_economics: bool`, `recompute_verdict: bool`

**Spec §26.5:** affected-only, with a manual full re-run available. **Pure** — lives in `engines/`, so the purity guard applies.

- [ ] **Step 1: Write the failing test**

```python
BINDINGS = {"price_monthly": "a-price", "delivery_cost": "a-delivery"}
SENS = [{"variable": "price_monthly", "elasticity": 3.0},
        {"variable": "delivery_cost", "elasticity": 1.0}]


def test_a_changed_assumption_includes_itself():
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert "a-price" in got.assumptions


def test_a_parameter_bound_to_the_changed_assumption_is_affected():
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.parameters == {"price_monthly"}


def test_unrelated_parameters_are_not_recomputed():
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert "delivery_cost" not in got.parameters


def test_economics_is_recomputed_when_a_parameter_moved():
    """A parameter change moves every breakpoint, so the solve must re-run."""
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.recompute_economics is True


def test_the_verdict_is_always_recomputed():
    """Confidence depends on every assumption's status, so it always moves."""
    got = affected_closure("a-orphan", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.recompute_verdict is True


def test_an_assumption_bound_to_no_parameter_skips_the_economics_solve():
    got = affected_closure("a-orphan", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.parameters == set() and got.recompute_economics is False


def test_the_closure_is_deterministic():
    a = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    b = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert a == b


def test_multiple_parameters_bound_to_one_assumption_are_all_included():
    bindings = {"price_monthly": "a-price", "wtp_annual": "a-price"}
    got = affected_closure("a-price", parameter_bindings=bindings, sensitivity=SENS)
    assert got.parameters == {"price_monthly", "wtp_annual"}
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement** (pure, imports only `schemas`)
- [ ] **Step 4: Verify it passes and the purity guard still passes**
```bash
cd apps/api && uv run pytest tests/engines/test_affected.py tests/engines/test_purity.py -v
```
- [ ] **Step 5: Commit** — `git commit -m "feat(engines): affected-only recompute closure"`

---

### Task 6.4: Result logging — the mechanical update

**Files:** Create `jury/api/routers/experiments.py`, `jury/graph/rerun.py`; Test `tests/api/test_result_logging.py`

**Interfaces:**
- `POST /experiments/{id}/result` body `{result_value: float, result_notes?: str}` → `202` with `{experiment_status, assumption_status, version, diff}`
- `async def rerun_affected(project_id, run_id, changed_assumption_id) -> RunState`

**F14:** *"Result logging; mechanical status update against criterion; affected-only re-run; immutable versions; rendered causal diff."*

**PRD §17.3:** *"`POST /experiments/{id}/result` is idempotent on `(experiment_id, result_value)`."*

**The word that matters is *mechanical*.** PRD §7.10: *"The affected assumption's status changes **mechanically** against the pre-registered criterion."* No model is consulted. A test asserts zero LLM calls on the status transition.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/api/test_result_logging.py
async def test_logging_a_failing_result_flips_the_assumption_to_refuted(client, auth, exp):
    """PRD §7.10 worked example: 3/20 pre-paid against a criterion of >=4/20."""
    r = await client.post(f"/experiments/{exp}/result",
                          json={"result_value": 3}, headers=auth)
    assert r.status_code == 202
    assert r.json()["experiment_status"] == "failed"
    assert r.json()["assumption_status"] == "refuted"


async def test_logging_a_passing_result_marks_the_experiment_passed(client, auth, exp):
    r = await client.post(f"/experiments/{exp}/result",
                          json={"result_value": 7}, headers=auth)
    assert r.json()["experiment_status"] == "passed"


async def test_the_boundary_value_passes(client, auth, exp):
    """>=4 means 4 passes. An off-by-one here rewrites the founder's conclusion."""
    r = await client.post(f"/experiments/{exp}/result",
                          json={"result_value": 4}, headers=auth)
    assert r.json()["experiment_status"] == "passed"


async def test_the_status_transition_consults_no_model(client, auth, exp, offline):
    """PRD §16.6: pre-registering the threshold makes the update mechanical
    rather than another model judgement."""
    before = offline.llm.calls
    await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                      headers=auth)
    # the rationale regeneration is allowed one call; the transition itself is zero
    assert offline.llm.calls - before <= 1
    assert await fetch_assumption_status(assumption_id) == "refuted"


async def test_logging_is_idempotent_on_experiment_and_value(client, auth, exp):
    """PRD §17.3."""
    a = await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                          headers=auth)
    b = await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                          headers=auth)
    assert a.json()["version"] == b.json()["version"]


async def test_a_different_value_creates_a_new_version(client, auth, exp):
    a = await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                          headers=auth)
    b = await client.post(f"/experiments/{exp}/result", json={"result_value": 9},
                          headers=auth)
    assert b.json()["version"] == a.json()["version"] + 1


async def test_logging_writes_a_new_version_with_a_diff(client, auth, exp):
    r = await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                          headers=auth)
    assert r.json()["version"] >= 2
    assert r.json()["diff"]


async def test_the_bound_parameter_provenance_changes(client, auth, exp, pool):
    """PRD §7.10: 'This moved price_monthly from founder_asserted Rs 499 to
    evidence_backed Rs 249'."""
    await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                      headers=auth)
    diff = (await fetch_latest_version(project_id))["diff"]
    assert any(d["type"] == "parameter_provenance_change" for d in diff)


async def test_the_breakpoint_moves(client, auth, exp, pool):
    await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                      headers=auth)
    diff = (await fetch_latest_version(project_id))["diff"]
    assert any(d["type"] == "breakpoint_moved" for d in diff)


async def test_the_verdict_is_recomputed(client, auth, exp, pool):
    before = (await fetch_latest_verdict(project_id))["decision"]
    await client.post(f"/experiments/{exp}/result", json={"result_value": 0},
                      headers=auth)
    after = (await fetch_latest_verdict(project_id))["decision"]
    # Whether the DECISION changes depends on the fixture, so that is not
    # asserted. What is required is that a fresh verdict was computed rather
    # than the previous one carried forward.
    assert (await count_verdicts(project_id)) >= 2
    assert after in DECISIONS


async def test_no_evidence_row_is_mutated_by_a_return_visit(client, auth, exp, pool):
    """P6 through the return visit — the place where a mutable design would
    have been tempting."""
    before = await fetch_all_evidence_rows(project_id)
    await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                      headers=auth)
    assert await fetch_all_evidence_rows(project_id) == before


async def test_the_rerun_is_affected_only_and_re_investigates_nothing(client, auth, exp, offline):
    """Spec §26.5: affected-only makes the diff a clean causal chain."""
    before_searches = offline.search.calls
    await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                      headers=auth)
    assert offline.search.calls == before_searches


async def test_the_rerun_completes_within_ninety_seconds(client, auth, exp):
    """PRD §17.1 target for a return-visit affected-only re-run."""
    started = time.perf_counter()
    await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                      headers=auth)
    assert time.perf_counter() - started < 90


async def test_a_result_on_another_users_experiment_is_refused(client, auth_b, exp):
    r = await client.post(f"/experiments/{exp}/result", json={"result_value": 3},
                          headers=auth_b)
    assert r.status_code in (403, 404)


async def test_a_non_numeric_result_is_rejected(client, auth, exp):
    r = await client.post(f"/experiments/{exp}/result",
                          json={"result_value": "lots"}, headers=auth)
    assert r.status_code == 422


async def test_a_manual_full_rerun_is_available(client, auth, project):
    """Spec §26.5: 'with a manual full re-run available.'"""
    r = await client.post(f"/projects/{project}/runs", json={"kind": "pivot_check"},
                          headers=auth)
    assert r.status_code == 202
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** Order inside the handler, strictly:
1. Load the experiment; check ownership through the project.
2. Idempotency: if `result_value` equals the stored one, return the existing version unchanged.
3. `status_for_result(criterion_spec, result_value)` → `experiments.status`, `result_value`, `logged_at`.
4. Set the target assumption's status: `passed → supported`, `failed → refuted`. **Mechanical** — from the criterion, not from a model.
5. `affected_closure(...)` → re-bind affected parameters → re-solve economics → re-run the jury node.
6. `build_snapshot` → `write_version`.
7. Return `202` with the diff.

- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(api): mechanical result logging with affected-only re-run"`

---

### Task 6.5: Versions API and the causal-diff UI

**Files:** Create `jury/api/routers/versions.py`, `apps/web/components/ledger/*`, `apps/web/app/projects/[id]/versions/page.tsx`; Test `tests/api/test_versions.py`, `apps/web/tests/ledger.test.tsx`

**Routes:** `GET /projects/{id}/versions`, `GET /projects/{id}/versions/{v}/diff`.

**The render target (PRD §7.10):**
> `pricing_wtp` moved **uncertain → refuted** because 3/20 pre-paid against a criterion of ≥4/20. This moved `price_monthly` from `founder_asserted ₹499` to `evidence_backed ₹249`, which moved the break-even delivery cost from ₹38 to ₹19. Verdict changed **PROCEED → PIVOT**.

**PRD §7.10 again:** *"The return visit UI shows the **diff**, not a new report."*

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/api/test_versions.py
async def test_versions_list_is_newest_first(client, auth, project):
    versions = (await client.get(f"/projects/{project}/versions", headers=auth)).json()
    assert [v["version"] for v in versions] == sorted(
        [v["version"] for v in versions], reverse=True)


async def test_a_version_diff_returns_typed_entries(client, auth, project):
    diff = (await client.get(f"/projects/{project}/versions/2/diff",
                             headers=auth)).json()
    assert all(d["type"] in DIFF_TYPES for d in diff["entries"])


async def test_the_diff_response_carries_the_causal_sentence(client, auth, project):
    body = (await client.get(f"/projects/{project}/versions/2/diff",
                             headers=auth)).json()
    assert body["causal_sentence"]
    assert "→" in body["causal_sentence"] or "->" in body["causal_sentence"]


async def test_version_one_diff_is_empty_not_an_error(client, auth, project):
    r = await client.get(f"/projects/{project}/versions/1/diff", headers=auth)
    assert r.status_code == 200 and r.json()["entries"] == []


async def test_a_nonexistent_version_returns_404(client, auth, project):
    assert (await client.get(f"/projects/{project}/versions/99/diff",
                             headers=auth)).status_code == 404


async def test_another_users_versions_are_not_readable(client, auth_b, project):
    assert (await client.get(f"/projects/{project}/versions",
                             headers=auth_b)).status_code in (403, 404)
```

```tsx
// apps/web/tests/ledger.test.tsx
it("renders the causal chain as one sentence, not a bullet list", () => {
  expect(screen.getByTestId("causal-sentence").textContent).not.toContain("\n");
});

it("renders the status transition with an arrow", () => {
  expect(screen.getByText(/uncertain\s*→\s*refuted/)).toBeInTheDocument();
});

it("renders the verdict change", () => {
  expect(screen.getByText(/PROCEED\s*→\s*PIVOT/)).toBeInTheDocument();
});

it("shows a diff rather than regenerating a report", () => {
  // PRD §2.2: a regenerated report is explicitly a failure mode
  expect(screen.queryByText(/full report/i)).toBeNull();
});

it("renders version one as the baseline with no diff", () => { ... });

it("shows the kill criterion beside the logged result so the comparison is visible", () => {
  // P9's payoff: the founder cannot rationalise an ambiguous result
  expect(screen.getByText(/≥\s*4\s*of\s*20/)).toBeInTheDocument();
  expect(screen.getByText(/logged:\s*3/i)).toBeInTheDocument();
});

it("disables the log-result form when the experiment has no kill criterion", () => {
  // P9 at the UI boundary
});
```

- [ ] **Step 2: Verify they fail**
- [ ] **Step 3: Implement.** The diff route calls `causal_sentence(entries)` from Phase 1 — the sentence is generated by the **pure engine**, not by an LLM, so it is reproducible and cannot drift between renders.
- [ ] **Step 4: Verify they pass**
- [ ] **Step 5: Commit** — `git commit -m "feat(web): version list and causal diff render"`

---

### Task 6.6: Markdown export

**Files:** Create `jury/api/routers/export.py`; Test `tests/api/test_export.py`

F15's PDF is cut (spec §4); Markdown is retained because it is cheap and it carries the citations, which is the point.

**Route:** `POST /projects/{id}/export` → `{format: "md"}` returning `text/markdown`.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_export_contains_every_evidence_citation(client, auth, project):
    """PRD §23: 'Every claim in the output is clickable and verifiable.'"""
    md = (await client.post(f"/projects/{project}/export", json={"format": "md"},
                            headers=auth)).text
    for url in await fetch_all_source_urls(project):
        assert url in md


async def test_the_export_contains_the_verdict_and_all_four_components(client, auth, project):
    md = (await client.post(...)).text
    for token in ("coverage", "mean_strength", "contradiction", "open_critical"):
        assert token in md


async def test_the_export_contains_every_kill_criterion(client, auth, project):
    """P9: 'Required non-null field before the plan can be exported.'"""
    md = (await client.post(...)).text
    for e in await fetch_experiments(project):
        assert e["kill_criterion"] in md


async def test_export_is_refused_when_an_experiment_has_no_kill_criterion(client, auth, project):
    """P9 enforced at the export boundary, exactly as PRD §4 specifies."""
    await insert_experiment_without_criterion(project)
    r = await client.post(f"/projects/{project}/export", json={"format": "md"},
                          headers=auth)
    assert r.status_code == 409


async def test_the_export_contains_the_breakpoint_sentences(client, auth, project):
    md = (await client.post(...)).text
    assert "becomes unviable" in md


async def test_another_users_project_cannot_be_exported(client, auth_b, project):
    assert (await client.post(f"/projects/{project}/export", json={"format": "md"},
                              headers=auth_b)).status_code in (403, 404)
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** Sections: pitch, archetype, assumptions with status and strength, coverage gaps, evidence grouped by chair with tier and **clickable URL**, conflicts with position deltas, economics with breakpoint sentences and parameter provenance, verdict with the four components and the formula, experiments with kill criteria, version history.
- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(api): markdown case-file export gated on P9"`

---

### Task 6.7: Phase gate — the return-visit demo beat

- [ ] **Step 1:** `cd apps/api && JURY_OFFLINE=1 uv run pytest -q`
- [ ] **Step 2:** `npm run test --workspace apps/web`
- [ ] **Step 3: Walk the §22 4:20 beat by hand.** Full offline run → note the verdict → log `3` against the `≥4 of 20` presale experiment → confirm on screen that the assumption flips, the parameter provenance moves, the breakpoint moves, the verdict recomputes, and the causal sentence renders. **Paste the rendered sentence verbatim into `CHANGELOG.md`** — that sentence is the demo.
- [ ] **Step 4:** Append to `CHANGELOG.md`, commit, push.

---

## Phase 6 exit criteria

- [ ] Snapshot is self-contained, JSON-serialisable, and stable across repeated builds
- [ ] Versions are dense, monotonic, and never overwritten
- [ ] Concurrent version writes do not duplicate a version number
- [ ] Affected closure includes the changed assumption and only its bound parameters
- [ ] The verdict is always recomputed; economics only when a parameter moved
- [ ] Purity guard still green after `engines/affected.py`
- [ ] Logging `3` against `≥4 of 20` flips `uncertain → refuted` **mechanically**
- [ ] The boundary value (`4`) passes
- [ ] The status transition itself consults **no** model
- [ ] Logging is idempotent on `(experiment_id, result_value)`; a different value makes a new version
- [ ] Parameter provenance change, breakpoint move and verdict recompute all appear in the diff
- [ ] **No evidence row is mutated by a return visit** (P6)
- [ ] The re-run is affected-only — **zero** new searches
- [ ] Re-run completes under 90s
- [ ] Cross-user result logging, version reads and exports are all refused
- [ ] Diff renders as **one sentence** with arrows, not a bullet list
- [ ] The kill criterion is shown beside the logged result
- [ ] Export carries every citation, every kill criterion, and the four components
- [ ] **Export is refused (409) when any experiment lacks a kill criterion** (P9)

> **Phase 0 carry-over:** Task 6.2 must add a migration giving `ledger_versions` the same
> three-layer immutability `evidence_items` received — `revoke update, delete, truncate`,
> row-level UPDATE/DELETE triggers, and a statement-level TRUNCATE trigger — plus a test per
> layer. Found during Phase 0 review: revoking only the obvious verbs leaves TRUNCATE open,
> and TRUNCATE bypasses both RLS and row-level triggers.
