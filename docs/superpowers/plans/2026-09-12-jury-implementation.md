# Jury Implementation Plan — Master

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Jury — an evidence-led startup validation system where five source-specialised investigators produce a citation-backed Evidence Ledger, a deterministic engine finds real contradictions, an executable economics model finds exact breakpoints, and a jury rules on the record or refuses to rule.

**Architecture:** Next.js 15 client reads Postgres directly through RLS and subscribes to Supabase Realtime for live evidence rows; a FastAPI + LangGraph orchestrator on Cloud Run owns all writes and run control as a durable, resumable state machine with two human-in-the-loop interrupts. All arithmetic and all conflict detection are deterministic Python over typed Pydantic contracts — the LLM structures text and writes prose, and never computes a number or decides a verdict.

**Tech Stack:** Python 3.12 · FastAPI · LangGraph (Postgres checkpointer) · Supabase (Postgres 15 + pgvector + Auth + Realtime + Storage) · LiteLLM → Groq · fastembed `bge-small-en-v1.5` · numpy + scipy · Upstash Redis · Next.js 15 + Tailwind + shadcn/ui + Recharts · uv · pytest · vitest

**Spec:** [`docs/superpowers/specs/2026-09-12-jury-design.md`](../specs/2026-09-12-jury-design.md) — which is itself a delta on [`docs/PRD.md`](../../PRD.md). **Executors must read both.**

---

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec and PRD.

### Product principles — enforced in code, not prompts (PRD §4)

| # | Principle | Enforcement point |
|---|---|---|
| P1 | **No source, no entry.** Evidence without a resolvable, *actually fetched* source URL is rejected at insert. | `retrieval/verify.py` pre-persist check: HTTP 2xx **and** excerpt substring-present in extracted text |
| P2 | Claims and evidence are different things. Founder assertions are assumptions, never evidence. | Separate tables; `assumptions.origin ∈ {founder, discovered}` |
| P3 | The ledger is the single source of truth. A chair speaks on screen only when it has written a ledger row. | UI subscribes to table CDC; no separate narration path exists |
| P4 | Coverage is measured against an external denominator. | `assumption_classes` is hand-seeded static SQL, **never** LLM-generated |
| P5 | The Jury may refuse to rule. | Verdict gate; below threshold `PROCEED`/`STOP` are structurally unreachable |
| P6 | Evidence is immutable. Corrections supersede, never update. | Postgres denies UPDATE/DELETE on `evidence_items` to **all** roles incl. service role |
| P7 | Debate only where conflict exists. | LangGraph conditional edge gated on deterministic rules |
| P8 | Economics is computed, not described. | Typed templates + numpy/scipy. **No LLM arithmetic anywhere** |
| P9 | Every experiment has a pre-registered kill criterion. | `experiments.kill_criterion` + `criterion_spec` NOT NULL before export |
| P10 | Corroboration must be independent. | `unique (project_id, dedup_hash)` |

### Hard version floors

- **Python 3.12** exactly (pinned in `apps/api/.python-version` and `pyproject.toml` `requires-python = ">=3.12,<3.13"`). Python 3.14 has no `onnxruntime` wheels and `fastembed` is load-bearing per PRD §15.3.
- **Node ≥ 20**, Next.js **15.x**, React **19.x**
- Postgres **15** with `vector` extension (Supabase CLI default)
- `pgvector` dimension is **384** (`bge-small-en-v1.5`), fixed everywhere

### Source tier weights (PRD §9.1) — exact values

| Tier | Weight | Persistable |
|---|---|---|
| 1 | `1.00` | yes |
| 2 | `0.80` | yes |
| 3 | `0.55` | yes |
| 4 | `0.30` (see tier-4 override below) | yes |
| 5 | `0.00` | **NO — rejected at insert** |

**Tier-4 per-variable override (spec §26.4):** variables matching `price_monthly`, `take_rate`, or prefix `wtp_` use weight `0.15`, not `0.30`. No variable ever exceeds `0.30` at tier 4.

### Evidence Confidence weights (PRD §9.3, spec §26.3)

`0.30 · coverage + 0.30 · mean_strength + 0.20 · (1 − min(1, contradiction)) + 0.20 · (1 − open_critical)`, times 100.

Defined **once** as `CONFIDENCE_WEIGHTS` in `engines/scoring.py`. Never inlined at a call site. `docs/SCORING.md` must state these were **chosen by judgement, not fitted**.

### Scope enumerations (PRD §12.2) — closed sets, no free text

- `scope_geo`: `IN` `US` `EU` `UK` `SEA` `MENA` `LATAM` `GLOBAL`
- `scope_segment`: `consumer` `prosumer` `smb` `mid_market` `enterprise` `public_sector`
- `scope_tier`: `free` `entry` `mid` `premium` `enterprise` (nullable)
- `scope_period`: `YYYY` or `YYYY-Qn`

**Overlap rule:** two scopes overlap iff every populated field either matches or one side is a superset. `GLOBAL` supersets any geo; a null tier supersets all tiers.

### Archetypes (closed set of 6)

`marketplace` · `subscription_saas` · `d2c` · `services` · `ad_consumer` · `hardware`
Seeded depth: first three at **10** assumption classes, last three at **5** (spec §26.1). 45 rows total.

### Naming and copy rules

- Verdicts are uppercase exactly: `PROCEED` `PIVOT` `STOP` `HUNG_JURY`
- Chairs are lowercase exactly: `market` `customer` `precedent` `dependencies` `economics`
- Conflict rules are `R1`–`R5`; conflict kinds are `founder_vs_world` `chair_vs_chair` `no_evidence` `scope_gap`
- Tagline, where rendered: **"Don't build it. Prove it."**
- Never render the word "score" for Evidence Confidence without its four components adjacent (PRD §9.3)

### Commit rules

- Conventional commits (`feat:` `fix:` `test:` `docs:` `chore:`)
- **NEVER add `Co-Authored-By: Claude`, `Generated with Claude Code`, or any Anthropic/Claude attribution to any commit message or PR body.** Explicit user instruction. Author is `ishaans04 <sharmaishaaan04@gmail.com>`.
- Commit after every green test cycle. Push to `origin main` at each phase boundary.

### Offline mode (spec §3) — non-negotiable shape

`JURY_OFFLINE=1` swaps **transport only**. Search, fetch, LLM and Redis each expose a Protocol with `Live` and `Fixture` implementations. Engines, scoring, gate and solver run byte-identical code in both modes. A fixture returns a canned HTTP body; a fixture **never** returns a canned verdict, strength, breakpoint or conflict.

### Budgets (PRD §17.2) — enforced, not advisory

| Resource | Per-run cap |
|---|---|
| Search queries | 35 total (market 8, customer 8, precedent 10, dependencies 6, economics 3) |
| Page fetches | 60 |
| LLM calls | ~120 |
| Embeddings | ~3000 chunks |

### Security (PRD §17.4)

- RLS on every user-owned table
- SSRF guard on **every** outbound fetch: block `localhost`, `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16` (cloud metadata), `::1`, and non-`http(s)` schemes. Target URLs are partly model-selected.
- **Fetched page content is data, never instructions.** Never interpolate fetched text into a position where it could act as a directive.
- Secrets only in env. `.env.example` commits key **names** with empty values.

---

## Phase index

Each phase is a separate plan file and produces working, independently testable software. The **cut line falls after Phase 5** — everything through Phase 5 ships regardless.

| Phase | Plan file | Deliverable | Gate |
|---|---|---|---|
| **0** | [phase-0-foundation.md](2026-09-12-jury-phase-0-foundation.md) | Monorepo, full schema + RLS + immutability, seeds, Pydantic contracts | `pytest` green; Postgres rejects `UPDATE evidence_items` |
| **1** | [phase-1-engines.md](2026-09-12-jury-phase-1-engines.md) | All deterministic engines, TDD, zero credentials | PRD §19.2 deterministic rows at 100% |
| **2** | [phase-2-llm.md](2026-09-12-jury-phase-2-llm.md) | LiteLLM gateway, repair loop, offline fixture harness, `run_events` | Graph skeleton completes with empty `.env` |
| **3** | [phase-3-retrieval.md](2026-09-12-jury-phase-3-retrieval.md) | Retrieval layer, tier rules, P1 verification, Market chair end to end | 50 fabricated names → 100% rejected |
| **4** | [phase-4-graph-boardroom.md](2026-09-12-jury-phase-4-graph-boardroom.md) | Full LangGraph, 5 chairs, auth, intake, hearing, live boardroom | Row → correct column ≤2s; reload preserves state |
| **5** | [phase-5-verdict.md](2026-09-12-jury-phase-5-verdict.md) | Cross-exam, economics UI, verdict + hung jury, experiments, trace viewer | Gate unreachability proven by test |
| — | — | **CUT LINE** | |
| **6** | [phase-6-ledger.md](2026-09-12-jury-phase-6-ledger.md) | Result logging, affected-only re-run, versions, causal diff | Result flips status mechanically; diff renders |
| **7** | [phase-7-deploy.md](2026-09-12-jury-phase-7-deploy.md) | Cloud Run + Vercel, README, SCORING.md, 3-company backtest | Clean machine can run it |

---

## Execution protocol

### Before every phase

1. Re-read **`docs/PRD.md`**, **`docs/superpowers/specs/2026-09-12-jury-design.md`**, and **`CHANGELOG.md`** in full.
2. Re-read the phase plan file.
3. Confirm the previous phase's gate command still passes.

This is a standing instruction from the user: *"always before proceeding to the next phase always iterate through all the documents and the changelog.md to never lose the context."*

### After every phase

1. Run the phase gate command; capture real output.
2. Append a `CHANGELOG.md` entry: what was built, files added, the gate command, its **actual** output, and **any deviation from PRD.md with its reason**.
3. Commit and push to `origin main`.

### Per-task protocol (subagent-driven)

1. Dispatch a fresh subagent with the task text, the Global Constraints section, and the spec paths.
2. Subagent works TDD: failing test → verify it fails → minimal implementation → verify it passes → commit.
3. Two-stage review before accepting: correctness review, then simplification review.
4. Mark the task's checkboxes complete in the phase plan file.

### Standing prohibitions

- **No stubs, no scaffolding, no `pass  # TODO`.** A task is done when it is implemented and tested, not when its shape exists. (User: *"without scaffolding anything and completing each phase thoroughly"*.)
- No LLM arithmetic. Ever. If a number can be computed, compute it (P8).
- No mutation of `evidence_items`.
- No runtime generation of `assumption_classes`.
- No Claude/Anthropic attribution in commits.
