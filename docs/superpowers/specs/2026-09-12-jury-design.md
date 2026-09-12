# Jury — Build Design Decisions

> **Status:** Approved 2026-09-12
> **Parent spec:** [`docs/PRD.md`](../../PRD.md) — sections §1–§19 are the authoritative product design and are **not** restated here.
> **Purpose of this document:** resolve PRD §26's six open questions, record the 2-day scope cuts, and lock the decisions the implementation plan argues from.

This document is a **delta**. Where it is silent, PRD.md governs. Where it contradicts PRD.md, this document governs, and the contradiction is called out explicitly.

---

## 1. Constraint envelope

| Constraint | Value | Consequence |
|---|---|---|
| Calendar budget | **2 days** | PRD §20's M0–M7 (a ~3-week plan) is compressed to 7 phases; the cut line moves from after M5 to after Phase 5. |
| Credentials available at build start | **None** | Every external dependency sits behind an interface with a recorded fixture. See §3, Offline Mode. |
| Dev posture | **Local-first** | Supabase CLI on Docker 29.7.2. Hosted Supabase is not used during development. |
| Deploy target | Cloud Run (`jury-api`) + Vercel (`jury-web`) | Phase 7 only. |
| Attribution | **No Claude/Anthropic co-author trailers on any commit** | Explicit user instruction; overrides harness default. |

### 1.1 Honest scope statement

The full PRD is not achievable in 2 days. This build deliberately preserves the **deterministic** core — conflict engine, scoring model, verdict gate, economics solver, experiment generator, diff engine — because those are simultaneously the product's differentiator (PRD §2.3, §23.1 slide 8) and the cheapest thing to build per unit of credibility. Retrieval *breadth* is what gets trimmed, and PRD §18 already specifies graceful degradation for exactly that: a missing source becomes a documented absence, which is a valid ledger state.

---

## 2. PRD §26 open questions — resolutions

Each adopts the PRD's own recommendation. Rationale is recorded so the decision is auditable later.

### §26.1 Archetype breadth vs depth → **3 deep + 3 minimum-viable**

- **Deep (10 classes each):** `marketplace`, `subscription_saas`, `d2c`
- **Minimum-viable (5 classes each):** `services`, `ad_consumer`, `hardware`
- Detection always resolves to one of the six with a confidence value, and the founder can override. **Nothing hard-fails on an unsupported model** — that was the entire point of the recommendation.
- Total seeded rows: 45. This is hand-authored static data and is **never** LLM-generated (PRD P4). PRD §25 names "coverage score becomes self-graded" as the one shortcut that would hollow out the product.

### §26.2 Target scope capture → **explicit at intake, inferred default**

`projects.target_scope` is a required intake field rendered as four enum selects (geo / segment / tier / period, per PRD §12.2). The archetype-detection call also returns an inferred scope which pre-fills those selects. The founder confirms or changes them.

Rationale: R5 (scope gap) is only meaningful against a scope the founder actually endorsed. An inferred-but-unconfirmed scope would make "evidence exists but none covers your target" an accusation the founder never agreed to.

### §26.3 Confidence weights → **ship 0.30/0.30/0.20/0.20, publish as chosen**

Weights live in **one** module-level constant, not scattered at call sites, so the backtest can vary them without touching logic. `docs/SCORING.md` states verbatim that the split was **chosen by judgement, not fitted to data**. Publishing the provenance of the weights is itself the credibility claim (PRD §9.3).

### §26.4 Tier-4 weight → **0.30 baseline with a per-variable override**

A `TIER4_VARIABLE_OVERRIDES` map discounts forum anecdote for variables where stated intent is known-unreliable:

| Variable class | Tier-4 weight | Reason |
|---|---|---|
| `price_monthly`, `wtp_*`, `take_rate` | **0.15** | Stated willingness to pay is notoriously unreliable (PRD §26.4). |
| everything else | 0.30 | PRD §9.1 baseline. |

This is a *narrowing* of tier-4's influence, never a widening. No variable receives a tier-4 weight above 0.30.

### §26.5 Return-visit re-run scope → **affected-only, with manual full re-run**

`POST /experiments/{id}/result` triggers a re-run limited to the transitive downstream closure of the changed assumption: the assumption's status, evidence strength, any model parameter citing it, breakpoints, sensitivity, confidence, verdict. A `POST /projects/{id}/runs` with `kind=pivot_check` remains available for a full re-run.

Rationale: affected-only makes the diff a clean causal chain (PRD §7.10's single-sentence render) rather than a wall of incidental churn. Second-order effects are recoverable via the manual full re-run.

### §26.6 Retention testability → **flagged proxy, limitation stated in-product**

No 30-day experiment measures retention honestly. The experiment generator emits a `documented_proxy` method for retention variables carrying an explicit `limitation` field, and the experiment card renders that limitation as visible text. The product states the methodological gap rather than papering over it.

---

## 3. Offline mode — a first-class design decision

**Problem:** the build starts with zero credentials, so nothing could otherwise be verified end to end.

**Decision:** every outbound integration — search providers, HTTP fetch, LLM calls, Redis — sits behind a narrow Python Protocol with two implementations: `Live` and `Fixture`. `JURY_OFFLINE=1` selects `Fixture` for all of them. The full LangGraph pipeline runs start-to-finish against an empty `.env`.

This earns its place three times over:

1. **Build-time:** all seven phases are verifiable without waiting on credential provisioning.
2. **Demo-time:** PRD §25 asks for "a recorded fallback run available" for when Groq throttles during judging. This *is* that, with no extra work.
3. **Test-time:** deterministic fixtures are what let PRD §19.2's component evals score the 100% they are required to score.

**Non-negotiable:** offline mode substitutes *transport*, never *logic*. The conflict engine, scoring, verdict gate and economics solver run identical code in both modes. A fixture supplies a canned HTTP response; it never supplies a canned verdict.

### 3.1 Keyless-by-default providers

Two retrieval sources need no credential at all (PRD §11.1) and therefore work live from day one:

- **HN Algolia** (`hn-algolia`) — unlimited, keyless → Customer chair
- **Wayback CDX** (`wayback`) — free, keyless → Precedent chair death verification

Credential unblocking order, each flipping one chair from fixture to live: **Supabase → Groq → Brave → Exa → Reddit → Tavily → Upstash**.

---

## 4. Scope cuts beyond PRD §20.1

PRD §20.1 already cuts Monte Carlo, multi-round debate, teams, a sixth chair, the code sandbox, and external observability. These are **additional**, forced by the 2-day envelope.

| Cut | PRD ref | Why survivable |
|---|---|---|
| **Qdrant precedent corpus** | §11.2 dec. 3 | pgvector serves both workloads. §11.2 concedes pgvector-for-everything is "workable", losing only hybrid BM25+dense tuning. Qdrant earns its place once the corpus compounds *across users* — that is Roadmap (§24), not day two. Removes a managed service and a credential. |
| **Playwright `jury-render` service** | §16.1 tier 3 | Fetch degrades to trafilatura → Jina Reader. Jina Reader is keyless and handles most JS-rendered markup. Removes a deployed service and neutralises the §25 "Playwright bloats the image" risk. Fetch tier 3 is left as a documented extension point, not deleted. |
| **F15 PDF export** | §8 | P1. Absent from the §22 demo script. Markdown export is retained (it is ~20 lines). |
| **F16 conflict graph (React Flow)** | §8 | P1. Conflicts are fully legible as a list with position deltas; the graph is presentation, not mechanism. |
| **F18 read-only share link** | §8 | P2. |
| **F19 backtest: 10 companies → 3** | §19.1 | Keeps deck slide 9 honest by reporting `n=3` explicitly rather than fabricating ten. The harness itself is built to take N, so extending is data entry, not code. |

### 4.1 What is explicitly **not** cut

Enumerated because these are the load-bearing claims, and cutting any of them would make the product a different product:

- P1 pre-persist fetch verification, including the excerpt-present-in-extracted-text check (PRD §18 calls it non-optional)
- P6 insert-only `evidence_items`, enforced at the database for **all** roles including service role
- P10 `dedup_hash` uniqueness
- All of R1–R5, deterministic, no LLM (§16.3)
- The verdict gate with `HUNG_JURY` structurally unreachable-below-threshold (§9.4, P5)
- `brentq` breakpoints + elasticity sensitivity + parameter provenance (§16.5, P8)
- Pre-registered `criterion_spec` on every experiment (§16.6, P9)
- Ledger versioning and the causal diff (§16.8) — PRD §20 warns retrofitting immutability is a rewrite, so it lands in Phase 0

---

## 5. Toolchain decisions

| Decision | Value | Rationale |
|---|---|---|
| Python | **3.12** (pinned via uv) | 3.14.5 is the machine default but `onnxruntime` (required by `fastembed`) publishes no 3.14 wheels; scipy/psycopg wheel coverage is also incomplete. PRD §15.3 makes local fastembed load-bearing, so this is not optional. |
| Node package manager | **npm** | `pnpm` is not installed. The monorepo has two JS-free Python packages and one Next.js app; npm workspaces are sufficient and avoid a toolchain detour. |
| Python package manager | **uv** 0.12.5 | Already installed. Fast, lockfile-based, handles the 3.12 pin without a separate pyenv. |
| Local database | **Supabase CLI on Docker** | Docker 29.7.2 verified working. Gives real Postgres + pgvector + Auth + Realtime + RLS locally, which means RLS and Realtime are exercised from Phase 0 rather than discovered at deploy. |
| Test runner (api) | **pytest** | |
| Test runner (web) | **vitest** + Playwright for the one E2E auth round-trip | |

---

## 6. Architecture units and boundaries

Decomposition follows PRD §21.4. The boundary that matters most: **`engines/` must not import `retrieval/`, `llm/`, or any client.** Every engine is a pure function over typed inputs. This is what makes PRD §19.2's "deterministic components must score 100%" testable at all, and it is why the engines can be built in Phase 1 before a single credential exists.

```
apps/api/jury/
├── schemas/      pydantic contracts. imports: nothing internal.
├── engines/      scope · dedup · conflict · scoring · economics · experiments · diff
│                 PURE. imports: schemas only. no I/O, no clients, no DB.
├── llm/          gateway · model map · repair loop · prompt registry
├── retrieval/    search routing · fetch tiers · canonicalisation · SSRF guard · tier rules
├── chairs/       market · customer · precedent · dependencies · economics
│                 imports: schemas, llm, retrieval. never engines' internals.
├── graph/        nodes · edges · checkpointer · idempotency
├── db/           repositories. the only module that writes SQL.
└── api/          FastAPI routers. thin. no logic.
```

A chair is a composition of `retrieval` + `llm` that emits `ClaimRecord`s. It performs no scoring and detects no conflicts — those belong to `engines/`, which run after fan-out completes. This keeps a chair replaceable and independently testable.

---

## 7. Verification strategy

Per phase, a named command that must pass before the next phase begins. No phase is "done" on inspection.

| Phase | Gate |
|---|---|
| 0 | `uv run pytest` green; migrations apply to local Supabase; a direct `UPDATE evidence_items` is **rejected by Postgres** |
| 1 | Every PRD §19.2 deterministic row at 100%: scope overlap, conflict engine, economics solver, kill-criterion evaluation |
| 2 | Full graph completes with an **empty `.env`** under `JURY_OFFLINE=1` |
| 3 | Hallucination guard: 50 fabricated company names injected into model output, **100% rejected at insert** |
| 4 | Five chairs land rows; Realtime insert → correct boardroom column ≤2s; reload preserves state |
| 5 | Gate test: no input combination below threshold can produce `PROCEED` or `STOP` |
| 6 | Logging a result flips assumption status **mechanically** against `criterion_spec` and renders a causal diff |
| 7 | Cold-start run completes within PRD §17.1 p95; README lets a clean machine run it |

---

## 8. Context discipline

Three documents are the context anchors, re-read in full before each phase begins:

1. **`docs/PRD.md`** — the product. Authoritative on *what* and *why*.
2. **`docs/superpowers/specs/2026-09-12-jury-design.md`** (this file) — the resolved decisions and cuts.
3. **`CHANGELOG.md`** — what has actually been built, per phase, with the verification output that proved it.

`CHANGELOG.md` records deviations explicitly. If an implementation detail diverges from PRD.md, the changelog says so and says why; drift that is written down is a decision, drift that is not is a bug.
