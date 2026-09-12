# Changelog

Running record of what has **actually** been built.

**Re-read this file in full — alongside [`docs/PRD.md`](docs/PRD.md) and [`docs/superpowers/specs/2026-09-12-jury-design.md`](docs/superpowers/specs/2026-09-12-jury-design.md) — before starting any phase.** That is a standing instruction, not a suggestion: these three documents are the only defence against drifting from the idea across a multi-phase build.

Every phase entry records:

1. **What was built** — files added or changed, task by task.
2. **The gate command** — the exact command, not a description of it.
3. **Its actual output** — pasted verbatim. Not "tests pass". The number.
4. **Deviations from `docs/PRD.md`** — what differs, and *why*.

Drift that is written down is a decision. Drift that is not is a bug.

---

## Planning — 2026-09-12

**Status:** plan complete, approved, not yet executed.

### Documents written

| File | Purpose |
|---|---|
| `docs/PRD.md` | Moved from repo root to its §21.4 home. Unmodified — it is the product's authority. |
| `docs/superpowers/specs/2026-09-12-jury-design.md` | Resolves PRD §26's six open questions; records the 2-day scope cuts and the toolchain decisions. |
| `docs/superpowers/plans/2026-09-12-jury-implementation.md` | Master plan: global constraints, the ten product principles with their enforcement points, phase index, execution protocol. |
| `docs/superpowers/plans/2026-09-12-jury-phase-0-foundation.md` | Schema, RLS, database-enforced immutability, 45 seeded assumption classes, Pydantic contracts. |
| `docs/superpowers/plans/2026-09-12-jury-phase-1-engines.md` | Every deterministic engine, TDD, zero credentials. |
| `docs/superpowers/plans/2026-09-12-jury-phase-2-llm.md` | LiteLLM gateway, five-stage repair loop, offline fixture transport, `run_events`. |
| `docs/superpowers/plans/2026-09-12-jury-phase-3-retrieval.md` | SSRF guard, tier rules, tiered fetch, P1 verification, embeddings, Market chair. |
| `docs/superpowers/plans/2026-09-12-jury-phase-4-graph-boardroom.md` | LangGraph, five chairs, auth, intake, hearing, live boardroom. |
| `docs/superpowers/plans/2026-09-12-jury-phase-5-verdict.md` | Cross-examination, economics, verdict + hung jury, experiments, trace viewer. **Cut line.** |
| `docs/superpowers/plans/2026-09-12-jury-phase-6-ledger.md` | Result logging, affected-only re-run, versions, causal diff, export. |
| `docs/superpowers/plans/2026-09-12-jury-phase-7-deploy.md` | Container, Cloud Run + Vercel, README, scoring docs, 3-company backtest. |

### Decisions locked

**PRD §26 open questions** — all six resolved by adopting the PRD's own recommendations. See spec §2 for the reasoning behind each.

| # | Question | Resolution |
|---|---|---|
| 1 | Archetype breadth vs depth | 3 deep (10 classes) + 3 minimum-viable (5 classes), detect-with-override |
| 2 | Target scope capture | Explicit at intake, pre-filled with an inferred default |
| 3 | Confidence weights | Ship 0.30/0.30/0.20/0.20, published as **chosen, not fitted** |
| 4 | Tier-4 weight | 0.30 baseline; WTP-class variables discounted to 0.15 |
| 5 | Return-visit re-run scope | Affected-only, with a manual full re-run |
| 6 | Retention testability | Flagged `documented_proxy`, limitation stated in-product |

**Scope cuts beyond PRD §20.1**, forced by the 2-day envelope — all recorded in spec §4 with justification:

- Qdrant precedent corpus → pgvector serves both workloads
- Playwright `jury-render` service → trafilatura → Jina Reader
- F15 PDF export → Markdown retained
- F16 conflict graph, F18 share link → cut
- F19 backtest: 10 companies → 3, reported honestly as `n=3`

**Not cut, and enumerated in spec §4.1** because cutting any would make this a different product: P1 pre-persist verification, P6 insert-only evidence, P10 dedup uniqueness, all of R1–R5, the verdict gate with a structurally unreachable `PROCEED`/`STOP`, `brentq` breakpoints with parameter provenance, pre-registered kill criteria, and ledger versioning with the causal diff.

**Toolchain** — Python **3.12** (not the machine's 3.14: `onnxruntime` publishes no 3.14 wheels and `fastembed` is load-bearing per PRD §15.3), uv, npm, Supabase CLI on Docker 29.7.2, pytest + vitest.

**Offline mode as a first-class design decision** (spec §3) — every outbound integration sits behind a Protocol with `Live` and `Fixture` implementations. `JURY_OFFLINE=1` runs the entire pipeline against an empty `.env`. It substitutes *transport*, never *logic*: a fixture returns a canned HTTP body and never a canned verdict, strength, breakpoint or conflict. This serves the build (no waiting on credentials), the demo (it is the recorded fallback PRD §25 asks for), and the tests (deterministic fixtures are what let PRD §19.2's components score their required 100%).

### Deviations from `docs/PRD.md` identified during planning

Recorded now so they are decisions rather than surprises. Each is revisited at the phase that implements it.

| # | Deviation | Phase | Reason |
|---|---|---|---|
| D1 | `evidence_items.superseded_by` points **forward** from the new row to the row it replaces, inverting PRD §12's implied direction | 0 | An insert-only table cannot write a column on an existing row. "Current" resolves as rows not referenced by any other row's `superseded_by`. |
| D2 | Added CHECK constraint `discovered_by_matches_origin` on `assumptions` | 0 | P2 integrity: a discovered assumption must name its chair, and a founder assumption must not. |
| D3 | Added CHECK `sources.http_status between 200 and 299` | 0 | P1 at the database level rather than only in application code. |
| D4 | R4 (`no_evidence`) fires for `medium` criticality as well as `blocking`/`high`, while the verdict gate still uses `{blocking, high}` | 1 | Reporting a medium-criticality silence is informative; it does not affect the verdict. |
| D5 | No economics template for `ad_consumer` or `hardware`; they map to `saas_v1` and `d2c_v1` | 1, 5 | PRD §16.5/§20 specify four templates. The substitution is stored in `model_runs.template_key` so it is visible rather than silent. |
| D6 | Fetch tier 3 (Playwright) absent; chain is trafilatura → Jina Reader | 3 | Spec §4. Left as a documented extension point, not deleted. |
| D7 | No `QDRANT_*` or `RENDER_SERVICE_URL` in `.env.example` | 0 | Both services cut per spec §4. |

### Execution protocol

Sub-agent driven, one fresh agent per task, TDD within each task, two-stage review between tasks. Before each phase: re-read PRD, spec and this changelog in full, then re-confirm the previous phase's gate still passes.

**Commits carry no Claude or Anthropic attribution.** Author is `ishaans04 <sharmaishaaan04@gmail.com>`. Explicit user instruction; it overrides the harness default.

---

## Phase 0 — Foundation

_Not started._

## Phase 1 — Deterministic engines

_Not started._

## Phase 2 — LLM layer, offline transport, tracing

_Not started._

## Phase 3 — Retrieval, verification, Market chair

_Not started._

## Phase 4 — Graph, five chairs, auth, hearing, boardroom

_Not started._

## Phase 5 — Cross-examination, economics, verdict (cut line)

_Not started._

## Phase 6 — Living ledger

_Not started._

## Phase 7 — Deploy, document, backtest

_Not started._
