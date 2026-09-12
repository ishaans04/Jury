# Phase 4 — Graph, Five Chairs, Auth, Hearing, Live Boardroom

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **PRD:** §7 (flow), §10.1–10.2 (why orchestration and why the DB is the streaming layer), §13 (API), §14 (auth), §16.7 (precedent), §17.3 (idempotency), F1–F8

**Phase goal:** The pipeline exists as a durable state machine, all five chairs investigate in parallel, and a founder can log in, submit a pitch, edit the assumption hearing, and watch evidence rows land in five columns live.

**Why the graph cannot be a request handler (PRD §10.1, verbatim):** *"A run is minutes long, fans out five ways, conditionally branches, and pauses twice for human input — once at the assumption hearing, once for weeks at the return visit. That is a durable state machine with human-in-the-loop interrupts, not a web request."*

**Gate:** an evidence row inserted by a chair appears in the correct boardroom column within **2s**, and a page reload mid-run preserves state.

---

## File structure

| Path | Responsibility |
|---|---|
| `jury/graph/state.py` | `RunState` TypedDict |
| `jury/graph/nodes/archetype.py` | Archetype detection (F4) |
| `jury/graph/nodes/extract.py` | Assumption extraction + 3-axis scoring (F5) |
| `jury/graph/nodes/coverage.py` | Coverage gap report (F6) |
| `jury/graph/nodes/hearing.py` | `interrupt()` pause |
| `jury/graph/nodes/investigate.py` | `Send` fan-out ×5 |
| `jury/graph/nodes/reconcile.py` | Dedup + conflict persistence |
| `jury/graph/build.py` | Graph assembly + Postgres checkpointer |
| `jury/graph/idempotency.py` | Per-node Redis keys (PRD §17.3) |
| `jury/chairs/customer.py`, `precedent.py`, `dependencies.py`, `economics.py` | The other four chairs |
| `jury/api/main.py`, `deps.py`, `routers/*.py` | FastAPI surface (PRD §13) |
| `apps/web/` | Next.js 15 app |

---

### Task 4.1: Archetype detection and assumption extraction

**Files:** Create `jury/graph/state.py`, `nodes/archetype.py`, `nodes/extract.py`, `llm/prompts.py`; Test `tests/graph/test_extract.py`

**Interfaces:**
- `RunState` TypedDict: `run_id`, `project_id`, `pitch`, `artifacts`, `archetype`, `archetype_confidence`, `target_scope`, `assumptions`, `coverage_gaps`, `evidence_ids`, `conflicts`, `cross_exam_done`, `model_run`, `verdict`, `experiments`, `version`
- `ArchetypeResult(BaseModel)`: `archetype: Archetype`, `confidence: float`, `inferred_scope: Scope`, `reasoning: str`
- `ExtractionResult(BaseModel)`: `assumptions: list[AssumptionDraft]`
- `async def detect_archetype(state, *, transports, trace) -> dict`
- `async def extract_assumptions(state, *, transports, classes, trace) -> dict`
- `def coverage_gaps(classes: list[tuple[str, float, str]], assumptions) -> list[dict]`

**F5 acceptance:** *"≥8 assumptions on a typical pitch, each falsifiable and single-clause, scored on 3 axes, fully editable, run blocked until confirmed."*

**F6 acceptance:** *"Names every assumption class the pitch is silent on, before investigation begins."* PRD §7.3: *"Silence is a finding, and it is usually the first thing worth showing the founder."*

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/graph/test_extract.py — key cases
async def test_archetype_detection_returns_one_of_six_with_a_confidence(offline):
    out = await detect_archetype(state, transports=offline, trace=sink)
    assert out["archetype"] in set(Archetype)
    assert 0.0 <= out["archetype_confidence"] <= 1.0


async def test_archetype_detection_also_infers_a_target_scope():
    """Spec §26.2: explicit at intake, pre-filled with an inferred default."""
    out = await detect_archetype(state, transports=offline, trace=sink)
    assert out["inferred_scope"]["geo"] in set(Geo)


async def test_extraction_produces_at_least_eight_assumptions_on_a_typical_pitch():
    """F5 acceptance criterion."""
    out = await extract_assumptions(state, transports=offline, classes=CLASSES, trace=sink)
    assert len(out["assumptions"]) >= 8


async def test_every_assumption_is_scored_on_all_three_axes():
    out = await extract_assumptions(...)
    for a in out["assumptions"]:
        assert a["criticality"] in {"blocking", "high", "medium", "low"}
        assert a["uncertainty"] in {"unknown", "uncertain", "likely", "established"}
        assert a["falsifiability"] in {"testable_now", "testable_costly", "untestable"}


async def test_every_assumption_is_a_single_clause():
    """F5: 'each falsifiable and single-clause'. A conjunction is two assumptions."""
    out = await extract_assumptions(...)
    for a in out["assumptions"]:
        assert " and " not in a["statement"].lower() or a["statement"].count(",") == 0


async def test_founder_origin_is_the_default_and_no_chair_is_named():
    """P2 + the DB check constraint: origin=founder implies discovered_by is null."""
    out = await extract_assumptions(...)
    assert all(a["origin"] == "founder" and a.get("discovered_by") is None
               for a in out["assumptions"])


async def test_a_numeric_assertion_is_captured_as_variable_and_value():
    """This is what R3 needs. Without it, founder-vs-world can never fire."""
    state = {**base, "pitch": "We will charge 499 INR per month to Indian SMBs."}
    out = await extract_assumptions(...)
    priced = [a for a in out["assumptions"] if a.get("asserted_value")]
    assert priced and priced[0]["asserted_variable"] and priced[0]["asserted_value"] == 499


def test_coverage_gaps_name_every_silent_class():
    """F6. PRD §22 demo beat: 'your pitch is silent on supply liquidity and on
    regulatory'."""
    classes = [("m.demand", 1.0, "Do buyers look for this?"),
               ("m.supply", 1.0, "Will supply join?"),
               ("m.regulatory", 1.0, "Any licence needed?")]
    assumptions = [{"class_key": "m.demand"}]
    gaps = coverage_gaps(classes, assumptions)
    assert {g["key"] for g in gaps} == {"m.supply", "m.regulatory"}
    assert all(g["question"] for g in gaps)


def test_coverage_gaps_are_ordered_by_criticality_weight():
    """The founder should see the blocking silences first."""
    classes = [("a.low", 0.3, "q1"), ("a.block", 1.0, "q2")]
    gaps = coverage_gaps(classes, [])
    assert [g["key"] for g in gaps] == ["a.block", "a.low"]


def test_no_gaps_when_every_class_is_addressed():
    classes = [("a.x", 1.0, "q")]
    assert coverage_gaps(classes, [{"class_key": "a.x"}]) == []


async def test_a_dropped_extraction_does_not_produce_a_partial_assumption():
    """Phase 2's repair loop returning None must not become a malformed row."""
    out = await extract_assumptions(state, transports=broken_llm, classes=CLASSES, trace=sink)
    assert out["assumptions"] == []
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** Both nodes use `structured_report` with `role` from `TASK_ROLES` (`archetype_detection` → `fast`, `assumption_extraction` → `reasoning`). The extraction prompt embeds the archetype's `assumption_classes` **questions** so the model classifies against the real denominator rather than inventing categories — but the class list is passed in as data and never generated (P4). `coverage_gaps` is pure and sorts by `-crit_weight, key`.
- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(graph): archetype detection, assumption extraction, coverage gaps"`

---

### Task 4.2: The remaining four chairs

**Files:** Create `jury/chairs/customer.py`, `precedent.py`, `dependencies.py`, `economics.py`; Test `tests/chairs/test_customer.py`, `test_precedent.py`, `test_dependencies.py`, `test_economics_chair.py`

Each reuses `chairs/base.py`'s pipeline from Phase 3. What differs is the query strategy, the provider set and the prompt.

**Customer** (PRD §6): Reddit OAuth, HN Algolia, Google Play reviews, App Store listings. Output shape: quoted pain language, WTP evidence, refusal evidence, feature-gap patterns.

**Precedent** (PRD §16.7) — the weakest retrieval in the system by a wide margin, and the spec says to design accordingly:
- Widen from failures to **outcomes**. Successes are evidence about which conditions were load-bearing, and *"nobody has attempted this"* is itself a finding.
- **Death verification via Wayback CDX** — *"the single highest-value retrieval trick in the product and it is the answer to 'how do I know you didn't invent this company.'"*
- Anti-hallucination enforced in code, not prompt — already provided by Phase 3's `verify_claim`.

**Dependencies** (PRD §6.2) — the hard rule, because this chair *"has the thinnest natural corpus and will drift into opinion if unconstrained"*: may only emit claims that name a **specific external dependency** with a **citable property**. Complexity estimates, timeline guesses and architectural opinions must be rejected.

**Economics chair** (PRD §6): benchmark lookups only, budget 3. It does not solve the model — `engines/economics` does that in Phase 5.

- [ ] **Step 1: Write the failing tests — the constraint tests are the important ones**

```python
# tests/chairs/test_precedent.py
async def test_a_precedent_claim_without_a_fetchable_source_is_rejected(offline):
    """PRD §16.7: 'a precedent claim is rejected at insert unless it carries a
    resolvable source URL that was actually fetched and returned a 2xx.'"""
    result = await precedent.investigate(ctx_with_unfetchable_precedent)
    assert result.inserted == []
    assert result.rejected


async def test_wayback_snapshot_becomes_a_tier1_citable_death_date(offline):
    result = await precedent.investigate(ctx_with_wayback_fixture)
    rows = [await fetch_evidence(i) for i in result.inserted]
    archived = [r for r in rows if "web.archive.org" in r["source_url"]]
    assert archived and all(r["tier"] == 1 for r in archived)


async def test_no_precedent_found_is_recorded_as_a_finding_not_an_error(offline):
    """PRD §16.7: 'nobody has attempted this' is itself a finding, usually an
    unflattering one. PRD §25: accept 'no precedent found' as a valid finding."""
    result = await precedent.investigate(ctx_with_empty_search)
    assert result.inserted == []
    assert result.partial is False          # not a failure
    assert result.no_precedent_found is True


async def test_precedent_widens_to_successful_outcomes_not_only_failures(offline):
    result = await precedent.investigate(ctx_offline)
    outcomes = {(await fetch_evidence(i))["direction"] for i in result.inserted}
    assert outcomes <= {"supports", "refutes"}


# tests/chairs/test_dependencies.py
@pytest.mark.parametrize("opinion", [
    "This will be hard to build.",
    "The architecture would need a queue, which adds complexity.",
    "Expect about six months of engineering effort.",
])
async def test_dependency_opinions_are_rejected(opinion, offline):
    """PRD §6.2: 'This will be hard to build' is the old persona wearing a new
    badge. Rejected because no specific external dependency is named with a
    citable property."""
    result = await dependencies.investigate(ctx_with_llm_returning(opinion))
    assert result.inserted == []


@pytest.mark.parametrize("citable", [
    ("razorpay_licence", "Payment aggregators require RBI authorisation."),
    ("stripe_api_price", "Standard pricing is 2.9% plus 30 cents per charge."),
    ("api_rate_limit", "The endpoint is limited to 100 requests per minute."),
])
async def test_dependency_claims_naming_a_dependency_and_property_are_accepted(citable, offline):
    result = await dependencies.investigate(ctx_with_llm_returning(citable))
    assert result.inserted


async def test_a_dependency_claim_must_carry_a_variable_or_unit(offline):
    """A 'citable property' means a property with a value, not a sentence."""
    result = await dependencies.investigate(ctx_with_propertyless_claim)
    assert result.inserted == []


# tests/chairs/test_customer.py
async def test_customer_works_with_no_reddit_credentials(offline_no_reddit):
    """Spec §3.1: HN Algolia is keyless, so Customer degrades rather than dies.
    PRD §18: 'degrade to HN Algolia, which is keyless and unlimited.'"""
    result = await customer.investigate(offline_no_reddit)
    assert result.partial is False


async def test_forum_evidence_lands_at_tier4(offline):
    rows = [await fetch_evidence(i)
            for i in (await customer.investigate(ctx_offline)).inserted]
    forum = [r for r in rows if "reddit.com" in r["source_url"]
             or "ycombinator" in r["source_url"]]
    assert all(r["tier"] == 4 for r in forum)


async def test_wtp_claims_from_forums_are_discounted_in_scoring(offline):
    """Spec §26.4 wired end to end: a tier-4 price claim weighs 0.15, not 0.30."""
    from jury.engines.scoring import tier_weight
    assert tier_weight(4, "price_monthly") == 0.15
```

- [ ] **Step 2: Verify they fail**
- [ ] **Step 3: Implement.** `dependencies.py` adds a post-`ClaimRecord` guard: reject unless `variable` is non-null **and** `value_num`/`value_min`/`unit` is populated **and** the excerpt names a domain-bearing entity. `precedent.py` adds `no_precedent_found: bool` to `ChairResult` and a Wayback CDX pass that converts a candidate company URL into a snapshot URL, which then verifies at tier 1.
- [ ] **Step 4: Verify they pass**
- [ ] **Step 5: Commit** — `git commit -m "feat(chairs): customer, precedent, dependencies and economics chairs"`

---

### Task 4.3: LangGraph assembly with interrupt and fan-out

**Files:** Create `jury/graph/build.py`, `nodes/hearing.py`, `nodes/investigate.py`, `nodes/reconcile.py`, `graph/idempotency.py`; Test `tests/graph/test_graph.py`

**Interfaces:**
- `def build_graph(transports, pool, classes) -> CompiledStateGraph`
- `async def run_initial(project_id, run_id, pitch, target_scope) -> RunState`
- `async def resume_hearing(run_id, edited_assumptions) -> RunState`
- `def idempotency_key(run_id: str, node: str, salt: str = "") -> str`

**Topology (PRD §7 / §10):**
```
archetype → extract → coverage → [interrupt: hearing]
  → Send fan-out ×5 → reconcile (dedup + conflict)
  → [conditional] cross_exam → economics → jury → experiments → version
```

Phase 4 builds through `reconcile`; Phase 5 adds `cross_exam` onward.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/graph/test_graph.py — key cases
async def test_the_graph_pauses_at_the_hearing_and_writes_no_evidence(offline, pool):
    """F5: 'run blocked until confirmed'. PRD §7.3: 'Nothing proceeds without
    confirmation.'"""
    state = await run_initial(project_id, run_id, PITCH, TARGET)
    assert state["__interrupt__"]
    assert await count_evidence(project_id) == 0


async def test_the_interrupt_is_recorded_in_the_trace():
    await run_initial(...)
    assert any(r["event"] == "interrupt" for r in await fetch_run_events(run_id))


async def test_founder_edits_survive_the_resume(offline, pool):
    """F5: fully editable. The founder's edit must be what investigation uses."""
    await run_initial(...)
    edited = [{**a, "criticality": "blocking", "statement": "Edited statement here."}
              for a in original]
    state = await resume_hearing(run_id, edited)
    stored = await fetch_assumptions(project_id)
    assert any(a["statement"] == "Edited statement here." for a in stored)


async def test_a_deleted_assumption_is_not_investigated():
    state = await resume_hearing(run_id, original[:-1])
    assert len(await fetch_assumptions(project_id)) == len(original) - 1


async def test_a_founder_added_assumption_is_investigated():
    extra = {"statement": "Suppliers will accept a 20 percent commission.",
             "origin": "founder", "criticality": "blocking",
             "uncertainty": "unknown", "falsifiability": "testable_now"}
    await resume_hearing(run_id, original + [extra])
    assert any("20 percent commission" in a["statement"]
               for a in await fetch_assumptions(project_id))


async def test_all_five_chairs_run_and_each_lands_rows(offline, pool):
    """F7: all five run concurrently."""
    await resume_hearing(run_id, original)
    chairs = {r["chair"] for r in await fetch_evidence_rows(project_id)}
    assert chairs == {"market", "customer", "precedent", "dependencies", "economics"}


async def test_the_five_chairs_run_concurrently_not_sequentially(offline):
    """Send fan-out, not a loop. Measured by overlapping node_start windows."""
    await resume_hearing(run_id, original)
    events = await fetch_run_events(run_id)
    starts = [e for e in events if e["event"] == "node_start"
              and e["node"].startswith("chair:")]
    ends = [e for e in events if e["event"] == "node_end"
            and e["node"].startswith("chair:")]
    assert len(starts) == 5
    # at least one chair started before another finished
    assert min(e["ts"] for e in ends) > sorted(s["ts"] for s in starts)[1]


async def test_a_chair_failing_does_not_fail_the_run(offline):
    """PRD §18: degrade to 'less evidence' rather than 'crash'."""
    state = await resume_hearing_with_broken_chair(run_id, original)
    assert state["run_status"] != "failed"
    assert state["evidence_ids"]


async def test_a_replayed_node_short_circuits(offline):
    """PRD §17.3: every node writes an idempotency key before side effects;
    a replayed node short-circuits."""
    await resume_hearing(run_id, original)
    before = await count_evidence(project_id)
    await resume_hearing(run_id, original)          # replay
    assert await count_evidence(project_id) == before


async def test_the_run_resumes_from_the_last_completed_node_after_a_crash(offline, pool):
    """PRD §10.1: 'survives an instance dying mid-run'."""
    await run_initial(...)
    graph = build_graph(offline, pool, CLASSES)     # fresh instance, same thread_id
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert state.next                                # a pending node exists


async def test_reconcile_persists_conflicts_from_the_deterministic_engine(offline):
    await resume_hearing(run_id, original)
    conflicts = await fetch_conflicts(project_id)
    assert conflicts
    assert all(c["rule"] in {"R1", "R2", "R3", "R4", "R5"} for c in conflicts)


async def test_reconcile_uses_no_llm(offline):
    """PRD §7.5: 'Deterministic. No LLM.'"""
    before = offline.llm.calls if hasattr(offline.llm, "calls") else 0
    await reconcile(state, transports=offline, trace=sink)
    after = offline.llm.calls if hasattr(offline.llm, "calls") else 0
    assert after == before


async def test_discovered_assumptions_are_appended_during_investigation(offline):
    """PRD §7.3: 'The graph is append-only and writable during investigation.'"""
    await resume_hearing(run_id, original)
    rows = await fetch_assumptions(project_id)
    discovered = [a for a in rows if a["origin"] == "discovered"]
    assert all(a["discovered_by"] for a in discovered)


async def test_coverage_is_scored_after_investigation_not_before(offline):
    """PRD §7.3: 'Coverage is scored after investigation, not before.'"""
    state = await resume_hearing(run_id, original)
    assert state["coverage"] is not None
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement**
- `state.py` uses `Annotated[list, operator.add]` for `evidence_ids` and `discovered` so five concurrent `Send` branches merge instead of clobbering. This is the single most common LangGraph fan-out bug — get it right here.
- `hearing.py` calls `interrupt({"assumptions": ..., "coverage_gaps": ...})`.
- `investigate.py` returns `[Send("chair", {"chair": c, **state}) for c in CHAIRS]`.
- `idempotency.py` writes `kv.set(key, "1", 3600)` guarded by a `kv.get` check, keyed `idem:{run_id}:{node}:{salt}`.
- `build.py` uses `AsyncPostgresSaver.from_conn_string(settings.database_url)`; run `await checkpointer.setup()` once at startup.
- Each chair node is wrapped in try/except that records an `error` trace row and returns `{"partial_chairs": [chair]}` rather than propagating.

- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(graph): durable pipeline with hearing interrupt and five-way fan-out"`

---

### Task 4.4: FastAPI surface

**Files:** Create `jury/api/main.py`, `deps.py`, `routers/projects.py`, `runs.py`, `health.py`; Test `tests/api/test_routes.py`

**Routes for this phase (PRD §13):** `POST /projects`, `GET /projects`, `GET /projects/{id}`, `PATCH /projects/{id}`, `POST /projects/{id}/artifacts`, `POST /projects/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/hearing/confirm`, `POST /runs/{id}/cancel`, `GET /health`.

**PRD §13's architectural instruction, verbatim:** *"Reads that the client can satisfy directly through `supabase-js` with RLS (assumptions, evidence, conflicts, verdicts, versions) should go direct, not through FastAPI. The orchestrator owns writes and run control only."* So there is deliberately **no** `GET /projects/{id}/evidence` route — the client reads that table directly.

**Auth:** every route requires a Supabase JWT in `Authorization: Bearer`. The orchestrator validates it and uses the user's ID for writes so RLS applies to service-side writes too (PRD §13).

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/api/test_routes.py — key cases
async def test_health_needs_no_auth(client):
    assert (await client.get("/health")).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("POST", "/projects"), ("GET", "/projects"), ("GET", "/runs/abc"),
    ("POST", "/runs/abc/hearing/confirm"), ("GET", "/runs/abc/events"),
])
async def test_every_other_route_rejects_a_missing_token(client, method, path):
    r = await client.request(method, path, json={})
    assert r.status_code == 401


async def test_a_forged_token_is_rejected(client):
    r = await client.get("/projects", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_a_token_signed_with_the_wrong_secret_is_rejected(client):
    bad = jwt.encode({"sub": str(uuid4())}, "wrong-secret", algorithm="HS256")
    r = await client.get("/projects", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


async def test_an_expired_token_is_rejected(client):
    ...
    assert r.status_code == 401


async def test_create_project_returns_archetype_and_confidence(client, auth):
    """PRD §13: 'Create project from a pitch; returns detected archetype + confidence'."""
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH,
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 201
    body = r.json()
    assert body["archetype"] in ARCHETYPES and 0 <= body["archetype_confidence"] <= 1


async def test_a_pitch_under_200_chars_is_rejected(client, auth):
    """PRD §7.2: 200-2000 chars."""
    r = await client.post("/projects", json={"name": "X", "pitch": "too short",
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 422


async def test_a_pitch_over_2000_chars_is_rejected(client, auth):
    r = await client.post("/projects", json={"name": "X", "pitch": "x" * 2001,
                                             "target_scope": TARGET}, headers=auth)
    assert r.status_code == 422


async def test_target_scope_is_required_at_intake(client, auth):
    """Spec §26.2: explicit, with an inferred default."""
    r = await client.post("/projects", json={"name": "X", "pitch": PITCH}, headers=auth)
    assert r.status_code == 422


async def test_archetype_can_be_overridden(client, auth, project):
    """F4: user-overridable."""
    r = await client.patch(f"/projects/{project}", json={"archetype": "d2c"},
                           headers=auth)
    assert r.json()["archetype"] == "d2c"


async def test_an_invalid_archetype_is_rejected(client, auth, project):
    r = await client.patch(f"/projects/{project}", json={"archetype": "unicorn"},
                           headers=auth)
    assert r.status_code == 422


async def test_one_user_cannot_read_another_users_project(client, auth_a, auth_b):
    """RLS is the persistence guarantee (PRD §14.4), and it must hold through
    the orchestrator too."""
    created = (await client.post("/projects", json={...}, headers=auth_a)).json()
    r = await client.get(f"/projects/{created['id']}", headers=auth_b)
    assert r.status_code in (403, 404)


async def test_one_user_cannot_start_a_run_on_another_users_project(client, auth_a, auth_b):
    ...
    assert r.status_code in (403, 404)


async def test_run_events_returns_the_trace(client, auth, run):
    """F17: append-only trace visible in-app."""
    r = await client.get(f"/runs/{run}/events", headers=auth)
    assert r.status_code == 200
    assert all({"node", "event", "ts"} <= set(e) for e in r.json())


async def test_hearing_confirm_resumes_the_run(client, auth, run):
    r = await client.post(f"/runs/{run}/hearing/confirm",
                          json={"assumptions": EDITED}, headers=auth)
    assert r.status_code == 202


async def test_hearing_confirm_rejects_an_assumption_missing_an_axis(client, auth, run):
    bad = [{"statement": "A thing is true.", "origin": "founder"}]
    r = await client.post(f"/runs/{run}/hearing/confirm",
                          json={"assumptions": bad}, headers=auth)
    assert r.status_code == 422


async def test_cancel_retains_the_checkpoint(client, auth, run):
    """PRD §13: 'Cancel; checkpoint retained'."""
    await client.post(f"/runs/{run}/cancel", headers=auth)
    r = await client.get(f"/runs/{run}", headers=auth)
    assert r.json()["thread_id"]


async def test_there_is_no_evidence_read_route(app):
    """PRD §13: evidence reads go direct through supabase-js with RLS."""
    paths = {r.path for r in app.routes}
    assert not any(p.endswith("/evidence") for p in paths)


async def test_an_oversized_artifact_upload_is_rejected(client, auth, project):
    """PRD §17.4: artifact uploads scanned for size and MIME type."""
    r = await client.post(f"/projects/{project}/artifacts",
                          files={"file": ("big.pdf", b"x" * (25 * 1024 * 1024),
                                          "application/pdf")}, headers=auth)
    assert r.status_code == 413


async def test_an_unsupported_artifact_mime_type_is_rejected(client, auth, project):
    r = await client.post(f"/projects/{project}/artifacts",
                          files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
                          headers=auth)
    assert r.status_code == 415
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** `deps.py` validates the JWT with `python-jose` against `settings.supabase_jwt_secret` (HS256, `audience="authenticated"`) and yields a `CurrentUser`. Run start is a background task; the route returns `202` with the `run_id`. Artifact upload caps at 10 MB and allows `application/pdf`, `application/vnd.openxmlformats-officedocument.presentationml.presentation`, `text/plain`.
- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(api): project and run control routes with JWT auth"`

---

### Task 4.5: Next.js — auth, dashboard, intake, hearing

**Files:** `apps/web/` — `package.json`, `next.config.ts`, `tailwind.config.ts`, `middleware.ts`, `lib/supabase/{client,server}.ts`, `app/login/page.tsx`, `app/auth/callback/route.ts`, `app/projects/page.tsx`, `app/projects/new/page.tsx`, `app/projects/[id]/page.tsx`, `components/hearing/*`; Test `apps/web/tests/*.test.ts`, `apps/web/e2e/auth.spec.ts`

**F1:** *"Email → link → session. **No password field exists anywhere in the product.** Session persists ≥30 days."*

**PRD §14.2:** four screens total for the entire auth and navigation surface — `/login`, `/auth/callback`, `/projects`, `/projects/{id}`.

- [ ] **Step 1: Write the failing tests**

```ts
// apps/web/tests/auth.test.ts
it("renders no password input anywhere in the login tree", () => {
  const { container } = render(<LoginPage />);
  expect(container.querySelector('input[type="password"]')).toBeNull();
});

it("calls signInWithOtp and never signInWithPassword", async () => {
  // F1: no password auth exists in the product
});

it("shows a check-your-inbox state after submit", async () => { ... });

it("rate-limits repeated magic-link requests for the same email", async () => {
  // PRD §14.3: a second Upstash token bucket caps requests per email per hour
  // to protect the free email quota
});

// apps/web/tests/hearing.test.ts
it("blocks the confirm button until every assumption has all three axes", () => { ... });
it("allows editing an assumption statement", () => { ... });
it("allows deleting an assumption", () => { ... });
it("allows adding a founder assumption", () => { ... });
it("renders coverage gaps with their questions before investigation", () => {
  // F6
});
it("shows the archetype with its confidence and an override control", () => {
  // F4
});

// apps/web/e2e/auth.spec.ts (Playwright)
test("unauthenticated /projects redirects to /login with a next param", async ({ page }) => {
  await page.goto("/projects");
  await expect(page).toHaveURL(/\/login\?next=%2Fprojects/);
});
```

- [ ] **Step 2: Verify they fail**
- [ ] **Step 3: Implement.** `@supabase/ssr` cookie sessions; `middleware.ts` refreshes on each request and redirects unauthenticated `/projects*` to `/login?next=...`. Session lifetime 30 days so a three-week return visit needs no re-auth (PRD §14.3). `/auth/callback` calls `exchangeCodeForSession`, upserts `profiles`, redirects to `/projects`.
- [ ] **Step 4: Verify they pass**
- [ ] **Step 5: Commit** — `git commit -m "feat(web): magic-link auth, dashboard, pitch intake and assumption hearing"`

---

### Task 4.6: The live boardroom

**Files:** `apps/web/components/boardroom/{Boardroom,ChairColumn,EvidenceCard}.tsx`, `hooks/useEvidenceStream.ts`; Test `apps/web/tests/boardroom.test.tsx`, `apps/web/e2e/boardroom.spec.ts`

**F8 acceptance:** *"Five columns; a row insert appears in the correct column within 2s; page reload and reconnect preserve state."*

**Why Realtime and not SSE (PRD §10.2):** *"It also makes P3 structural rather than aspirational: there is no way to render a chair speaking without a ledger row existing."*

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/tests/boardroom.test.tsx
it("renders exactly five columns in chair order", () => { ... });

it("routes an inserted row to its chair's column", async () => { ... });

it("renders a clickable source link on every evidence card", () => {
  // PRD §22 demo beat: "click a claim, the source opens"
  // PRD §2.3: every number is traceable to a fetchable URL
});

it("shows the source tier on every card", () => { ... });

it("renders nothing in a column with no rows rather than a fake placeholder", () => {
  // P3: a chair speaks ONLY when it has written a ledger row
});

it("marks a partial chair visibly so thin evidence is not mistaken for none", () => {
  // PRD §18: a chair marked partial lowers coverage
});

it("refetches on reconnect instead of trusting the socket", async () => {
  // PRD §18: "Client refetches on reconnect; state is in Postgres, not in the socket"
});

// apps/web/e2e/boardroom.spec.ts
test("an inserted evidence row appears in its column within 2s", async ({ page }) => {
  // F8's measurable criterion
});

test("reloading mid-run restores every row already written", async ({ page }) => { ... });
```

- [ ] **Step 2: Verify they fail**
- [ ] **Step 3: Implement.** `useEvidenceStream(projectId, runId)` does an initial `select` then `supabase.channel(...).on('postgres_changes', {event:'INSERT', table:'evidence_items', filter:`run_id=eq.${runId}`})`. On `SUBSCRIBED` after a drop, re-run the initial select — that is the reconnect guarantee. There is **no** client-side narration state: a card exists iff a row exists.
- [ ] **Step 4: Verify they pass**
- [ ] **Step 5: Commit** — `git commit -m "feat(web): live boardroom on realtime ledger rows"`

---

### Task 4.7: Phase gate

- [ ] **Step 1:** `cd apps/api && JURY_OFFLINE=1 uv run pytest -q`
- [ ] **Step 2:** `npm run test --workspace apps/web`
- [ ] **Step 3:** Start everything and run one full offline run end to end:
```bash
npx supabase start
cd apps/api && JURY_OFFLINE=1 uv run uvicorn jury.api.main:app --port 8000 &
npm run dev --workspace apps/web
```
Submit the demo pitch, confirm the hearing, and time the first row into the boardroom. Record the measured latency in `CHANGELOG.md` against F8's 2s and PRD §17.1's 20s first-row target.
- [ ] **Step 4:** `npx playwright test --workspace apps/web`
- [ ] **Step 5:** Append to `CHANGELOG.md`, commit, push.

---

## Phase 4 exit criteria

- [ ] ≥8 assumptions on the demo pitch, each single-clause and scored on three axes
- [ ] A numeric founder assertion is captured as `asserted_variable` + `asserted_value` (without which R3 can never fire)
- [ ] Coverage gaps named **before** investigation, ordered by criticality weight
- [ ] Graph pauses at the hearing with **zero** evidence rows written; `interrupt` appears in the trace
- [ ] Founder edits, deletions and additions all survive the resume
- [ ] All five chairs land rows; fan-out is concurrent, proven by overlapping trace windows
- [ ] A failing chair degrades the run to `partial`, never `failed`
- [ ] A replayed node writes no duplicate rows
- [ ] The run resumes from the last completed node with a fresh graph instance
- [ ] `reconcile` persists R1–R5 conflicts and makes **no LLM call**
- [ ] Discovered assumptions are appended mid-run, each naming its chair
- [ ] Coverage is scored **after** investigation
- [ ] Dependencies chair rejects opinions; accepts only a named dependency with a citable property
- [ ] Precedent rejects unfetchable companies; Wayback snapshots verify at tier 1; "no precedent found" is a finding
- [ ] Customer works with **no** Reddit credentials via keyless HN
- [ ] **No password input exists anywhere in the product**
- [ ] Unauthenticated `/projects*` redirects to `/login?next=`
- [ ] Every orchestrator route rejects missing, forged, wrong-secret and expired tokens
- [ ] Cross-user access to a project or run is refused
- [ ] No `/evidence` read route exists on the orchestrator
- [ ] Oversized and wrong-MIME artifact uploads rejected
- [ ] Boardroom: five columns, correct routing, **≤2s** to visible, reload and reconnect preserve state
- [ ] Every evidence card carries a clickable source URL and its tier
