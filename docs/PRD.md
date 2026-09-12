# Jury — Product Requirements Document

> **Don't build it. Prove it.**

| Field | Value |
|---|---|
| Product name | **Jury** |
| Tagline | Don't build it. Prove it. |
| Category | Evidence-led startup validation / AI research agent system |
| Submission | AI Builders Hackathon |
| Document version | 1.0 |
| Status | Approved for build |
| Author | Ishaan |

---

## 0. Document map

1. Problem statement
2. What Jury is / is not
3. Target users and jobs-to-be-done
4. Product principles (non-negotiable)
5. Domain model and glossary
6. The chairs and the Jury
7. End-to-end system flow
8. Feature specifications (F1–F14)
9. Scoring model and verdict gating
10. System architecture
11. Technology stack and rejected alternatives
12. Data model
13. API surface
14. Authentication and persistence
15. LLM layer
16. Engine specifications
17. Non-functional requirements
18. Failure modes and degradation
19. Evaluation and backtest
20. Build plan
21. Deployment runbook
22. Demo script
23. Hackathon deliverables mapping
24. Roadmap
25. Risk register
26. Open questions

---

## 1. Problem statement

Founders do not fail because nobody warned them. They fail because nobody checked.

An early-stage idea rests on a small number of load-bearing beliefs: that a specific customer has this pain, that they will pay above delivered cost, that the channel to reach them is affordable, that the thing is legal and technically possible, that the space is not already a graveyard. Most of these beliefs are never written down, never separated from the things the founder actually knows, and never tested before months of build time are committed.

The existing options all fail in the same way: they produce opinion where evidence is required.

| Option | Failure mode |
|---|---|
| Friends and peers | Politeness bias. They agree. |
| Generic chatbots | Sycophancy and averaged-out advice. No sources, no arithmetic, unfalsifiable output. |
| "AI advisor panel" tools | Five system prompts on one model. Same training data, same blind spots, so they converge instead of clashing. Theatre with a database attached. |
| Manual desk research | Correct but slow, unstructured, not reusable, and abandoned after the first week. |
| Accelerator feedback | High quality, but gated, late, and not continuous. |

The unmet need is not more advice. It is a **checkable record**: every belief the business depends on, what real-world evidence says about it, where that evidence came from, what remains unknown, and the cheapest test that would settle each remaining unknown.

---

## 2. What Jury is / is not

### 2.1 What it is

Jury is a virtual courtroom for an idea. The founder submits a pitch. Five specialist **investigators** go out and gather source-backed evidence about the pitch's load-bearing assumptions, each from a different corpus. A deterministic **conflict engine** finds genuine contradictions — most importantly between what the founder claims and what the world shows. Targeted cross-examination runs only where a real conflict exists. An **economics engine** builds and executes a real money model to find exact breakpoints. The **Jury** then rules on the record, and is permitted to refuse to rule.

The output is an **Evidence Ledger**: an append-only, versioned, citation-backed record that the founder returns to across a validation cycle, updating it with real experiment results.

### 2.2 What it is not

- Not a pitch-deck grader or pitch coach. The pitch is demoted to a set of founder-asserted claims that are expected to lose arguments against evidence.
- Not a success predictor. It does not forecast outcomes or rank ideas against each other.
- Not a replacement for customer conversations. It tells you which customers to talk to and exactly what to ask.
- Not a chatbot. There is no free-form advice surface.
- Not a report generator. A regenerated report is explicitly a failure mode; the ledger updates and diffs.

### 2.3 The one-line differentiator

Every number Jury produces is traceable to either a fetchable URL or an executed arithmetic model. Nothing else in this category can say that.

---

## 3. Target users and jobs-to-be-done

### 3.1 Primary persona — the pre-commitment builder

Solo founder, indie hacker, or two-person team, one to six weeks before committing serious time or money. Technically capable, allergic to fluff, has been burned by or is suspicious of AI advice. Uses Jury in the week they are deciding whether to start.

**JTBD:** "Before I spend three months on this, tell me what has to be true, what's already known, and what I should go find out first."

### 3.2 Secondary personas

| Persona | Use |
|---|---|
| Student / hackathon team | Validate before building; produce a defensible case file for a submission or a professor. |
| Accelerator applicant | Turn a pitch into an evidence-backed narrative; pre-empt partner diligence questions. |
| Intrapreneur / product lead | Justify or kill an internal new-product proposal with a record, not a deck. |
| Angel / micro-VC | Run a fast structured first-pass on inbound. Read-only consumer of the ledger. |

### 3.3 Anti-persona

Anyone looking for encouragement. Jury is designed to be uncomfortable. Users who want validation in the emotional sense will churn immediately, and that is acceptable.

### 3.4 Trigger moments

1. First run — new idea, pre-build.
2. Return visit — after interviews, a fake-door test, a supplier quote, a landing page.
3. Pivot check — after a material change to the model, re-run affected assumptions only.

---

## 4. Product principles (non-negotiable)

These are enforced in code, not in prompts. Each maps to a hard constraint in §12 or §16.

| # | Principle | Enforcement |
|---|---|---|
| P1 | **No source, no entry.** An evidence item without a resolvable, fetched source URL is rejected at insert. | DB constraint + pre-persist fetch verification. |
| P2 | **Claims and evidence are different things.** Founder assertions are assumptions, never evidence. | Separate tables; `assumptions.origin` vs `evidence_items`. |
| P3 | **The ledger is the single source of truth.** A chair speaks on screen only when it has written a ledger row. | UI subscribes to table changes; no separate narration path exists. |
| P4 | **Coverage is measured against an external denominator.** | `assumption_classes` is hand-seeded static data per archetype, never LLM-generated. |
| P5 | **The Jury may refuse to rule.** | Verdict gate in §9.4. Below threshold, `PROCEED`/`STOP` are structurally unreachable. |
| P6 | **Evidence is immutable.** Corrections happen by superseding, never by updating. | Insert-only `evidence_items`; `superseded_by` pointers. |
| P7 | **Debate only where conflict exists.** | Conditional graph edge gated on deterministic conflict rules. |
| P8 | **Economics is computed, not described.** | Typed templates + trusted numpy/scipy solver. No LLM arithmetic. |
| P9 | **Every experiment has a pre-registered kill criterion.** | Required non-null field on `experiments` before the plan can be exported. |
| P10 | **Corroboration must be independent.** The same source found twice never raises confidence. | Unique `dedup_hash` on `(canonical_url, variable, scope)`. |

---

## 5. Domain model and glossary

| Term | Definition |
|---|---|
| **Project** | A user's idea, persisting across runs. Owns the long-lived ledger. |
| **Run** | One execution of the pipeline against a project. Produces a ledger version. |
| **Pitch** | The founder's description of the idea, plus optional artifacts (deck, landing page, repo). |
| **Archetype** | The business-model class of the idea: marketplace, subscription SaaS, D2C commerce, services, ad-supported consumer, hardware. Determines the assumption checklist. |
| **Assumption class** | A category of belief that a given archetype *must* answer for. Hand-seeded. The coverage denominator. |
| **Assumption** | A single falsifiable proposition the business depends on. Has `origin` (founder or discovered), criticality, uncertainty, falsifiability, status. |
| **Evidence item** | A source-backed observation attached to an assumption, with a direction (supports/refutes), an optional variable and value, a typed scope, and a source tier. Immutable. |
| **Source tier** | Trustworthiness rank 1–4. Tier 5 (model prior) is not evidence and cannot be persisted. |
| **Scope** | Typed applicability of a claim: geography, segment, price tier, period. Prevents false conflicts. |
| **Conflict** | A detected contradiction. Four kinds: founder-vs-world, chair-vs-chair, no-evidence, scope-gap. |
| **Cross-examination** | A single targeted round where conflicting chairs must produce better evidence or concede. |
| **Position delta** | A recorded change in a chair's stance after cross-examination. |
| **Model run** | An executed unit-economics computation: parameters (with provenance), breakpoints, sensitivity ranking. |
| **Breakpoint** | The exact parameter value at which the business stops working. |
| **Provenance** | Whether a model parameter is `evidence_backed` or `founder_asserted`. Drives experiment selection. |
| **Experiment** | The cheapest test that would resolve an open assumption, with a pre-registered kill criterion. |
| **Kill criterion** | The pass/fail line, decided before the experiment is run. |
| **Verdict** | `PROCEED`, `PIVOT`, `STOP`, or `HUNG_JURY`. |
| **Evidence Confidence** | 0–100. How much is actually known. Separate from the verdict. |
| **Ledger version** | An immutable snapshot plus a computed diff against the prior version. |
| **Hung jury** | The refusal state. Insufficient evidence to rule, plus the three cheapest things to go learn. |

---

## 6. The chairs and the Jury

The five chairs are specialised by **evidence source and retrieval method**, not by personality. This is the central architectural commitment: five personas on one model share blind spots and converge; five corpora do not.

| Chair | Owns | Primary sources | Output shape |
|---|---|---|---|
| **Market** | Competitors, pricing, market structure, demand signal | Brave Search, live pricing pages (Playwright), company sites, Crunchbase-adjacent public pages, SEC EDGAR where applicable | Numeric price/plan claims, competitor counts, funding facts, launch dates |
| **Customer** | Pain, willingness to pay, objections, real-world language | Reddit OAuth, Hacker News Algolia, Google Play reviews, App Store listings, support/community forums | Quoted pain language, WTP evidence, refusal evidence, feature-gap patterns |
| **Economics** | Executable unit economics and sensitivity | Typed model templates + numpy/scipy; parameters sourced from other chairs' evidence where available | Breakpoints, sensitivity ranking, viability at evidence-backed parameters |
| **Precedent** | Companies that attempted this model — dead, pivoted, stalled, or succeeded — and why | Exa find-similar, Failory, autopsy.io, r/startups & r/SaaS postmortems, Indie Hackers, Product Hunt, Wayback CDX, Play Store last-update dates | Named companies with outcome, cause, date, and a verifiable source |
| **Dependencies** | What the idea requires from the outside world before it can exist | Third-party API docs and pricing pages, rate-limit documentation, regulatory registers, licensing requirements, supply/logistics pricing | Named external dependency with a citable property (cost, cap, licence, lead time) |
| **Jury** *(arbiter)* | Nothing. It never investigates. | — | Evidence Confidence, verdict or refusal, friction summary |

### 6.1 Output contract (all five chairs)

Every chair emits **only** typed claim records. No prose commentary is persisted or displayed except cross-examination transcripts.

```json
{
  "assumption_id": "uuid | null",
  "new_assumption": { "statement": "...", "class_key": "..." } ,
  "direction": "supports | refutes",
  "variable": "price_monthly | delivery_cost | churn_monthly | ...",
  "value_num": 149.0,
  "value_min": null,
  "value_max": null,
  "unit": "INR_per_month",
  "scope": { "geo": "IN", "segment": "smb", "tier": "entry", "period": "2026" },
  "confidence": 0.0,
  "source_url": "https://...",
  "source_tier": 1,
  "excerpt": "verbatim supporting text, ≤ 240 chars",
  "chair": "market"
}
```

`new_assumption` is how a chair introduces an assumption the extractor missed. See §7.3.

### 6.2 On the Dependencies chair

This chair has the thinnest natural corpus and will drift into opinion if unconstrained. "This will be hard to build" is the old persona wearing a new badge. Hard rule: Dependencies may only emit claims that name a **specific external dependency** with a **citable property**. Examples that pass: a payment aggregator licence requirement from a regulator's page; an API's published per-call price; a documented rate ceiling; a supplier's listed lead time. Examples that fail: complexity estimates, timeline guesses, architectural opinions.

---

## 7. End-to-end system flow

```
                        ┌──────────────────────────┐
                        │ 1. Auth (magic link)     │
                        └────────────┬─────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │ 2. Project + Pitch       │
                        │    + optional artifacts  │
                        └────────────┬─────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │ 3. Archetype detection   │
                        │    → assumption_classes  │
                        └────────────┬─────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │ 4. ASSUMPTION HEARING    │◄── interrupt(): founder
                        │    extract · classify    │    edits / confirms
                        │    coverage gap report   │
                        └────────────┬─────────────┘
                                     ▼
        ┌──────────┬──────────┬──────┴─────┬──────────┬──────────┐
        ▼          ▼          ▼            ▼          ▼          │
   ┌────────┐ ┌────────┐ ┌────────┐  ┌──────────┐ ┌──────────┐  │
   │ Market │ │Customer│ │Precede.│  │ Depend.  │ │Economics │  │  5. PARALLEL
   └───┬────┘ └───┬────┘ └───┬────┘  └────┬─────┘ └────┬─────┘  │  INVESTIGATION
       └──────────┴──────────┴────────────┴────────────┘         │
                             │  evidence_items inserted ─────────┼──► Realtime
                             ▼                                   │    → Boardroom UI
                  ┌──────────────────────┐                       │
                  │ 6. Dedup + Conflict  │                       │
                  │    engine (SQL)      │                       │
                  └──────────┬───────────┘                       │
                    conflicts?│                                  │
                 ┌─────no─────┴─────yes─────┐                    │
                 │                          ▼                    │
                 │            ┌──────────────────────────┐       │
                 │            │ 7. CROSS-EXAMINATION     │       │
                 │            │    1 round, targeted     │       │
                 │            │    → position deltas     │       │
                 │            └──────────┬───────────────┘       │
                 └──────────┬────────────┘                       │
                            ▼                                    │
                  ┌──────────────────────┐                       │
                  │ 8. Economics re-run  │                       │
                  │    breakpoints +     │                       │
                  │    sensitivity       │                       │
                  └──────────┬───────────┘                       │
                             ▼                                   │
                  ┌──────────────────────┐                       │
                  │ 9. JURY              │                       │
                  │    confidence + gate │                       │
                  │    verdict / hung    │                       │
                  └──────────┬───────────┘                       │
                             ▼                                   │
                  ┌──────────────────────┐                       │
                  │10. Experiment plan   │                       │
                  │    from sensitivity  │                       │
                  │    + kill criteria   │                       │
                  └──────────┬───────────┘                       │
                             ▼                                   │
                  ┌──────────────────────┐                       │
                  │11. Ledger version v1 │───────────────────────┘
                  └──────────┬───────────┘
                             ▼
                  ┌──────────────────────┐
                  │12. RETURN VISIT      │◄── weeks later
                  │    log results       │
                  │    → re-run affected │
                  │    → version diff    │
                  └──────────────────────┘
```

### 7.1 Stage 1 — Authentication

Email in, magic link out, session established, dashboard. Detail in §14.

### 7.2 Stage 2–3 — Pitch intake and archetype detection

The founder writes the idea in plain language (200–2000 chars) and may attach a landing page URL, a deck (PDF/PPTX), or a public repo URL. Attached artifacts are extracted to text, stored, and become tier-1 sources for founder-origin claims — this is how Jury catches "your deck claims real-time sync; your repo has no queue."

Archetype is classified into one of six classes with a confidence value. The founder can override. Archetype selects the `assumption_classes` checklist, which is the coverage denominator (P4).

### 7.3 Stage 4 — The Assumption Hearing

The pitch is decomposed into assumptions. Each is restated as a single falsifiable sentence and scored on three axes:

| Axis | Values | Meaning |
|---|---|---|
| Criticality | `blocking` / `high` / `medium` / `low` | If false, does the business still exist? |
| Uncertainty | `unknown` / `uncertain` / `likely` / `established` | How much is already known? |
| Falsifiability | `testable_now` / `testable_costly` / `untestable` | Can it be checked at all? |

The system then runs the checklist and reports **coverage gaps** — assumption classes the pitch is silent on. Silence is a finding, and it is usually the first thing worth showing the founder.

The graph is **append-only and writable during investigation**. Assumptions extracted from the pitch are created at the least-informed moment in the pipeline, so investigators are permitted to emit `new_assumption` mid-run. Coverage is scored *after* investigation, not before.

The graph pauses here via `interrupt()`. The founder can edit statements, change criticality, delete assumptions, and add their own. Nothing proceeds without confirmation.

### 7.4 Stage 5 — Parallel investigation

Five chairs run concurrently, each with a per-chair search budget (§17.2). Every finding is fetched, extracted, chunked, embedded, and persisted as an `evidence_item` with a verified source. Rows land in Postgres; Realtime pushes them to the correct boardroom column. A chair "speaking" is literally the rendering of a row (P3).

### 7.5 Stage 6 — Dedup and conflict detection

Deterministic. No LLM. Rules in §16.3.

### 7.6 Stage 7 — Cross-examination

Conditional edge. Fires only for `founder_vs_world`, `chair_vs_chair`, and numeric conflicts where the affected assumption is `blocking` or `high`. One round, maximum two chairs per conflict. Each participant must return at least one new tier-1 or tier-2 evidence item or formally concede. Position deltas are recorded and rendered.

### 7.7 Stage 8 — Economics

The model is (re-)executed with the best available parameters after cross-examination. Every parameter is tagged `evidence_backed` or `founder_asserted`. Breakpoints are solved, sensitivity is ranked.

### 7.8 Stage 9 — The Jury

Computes Evidence Confidence, applies the gate, issues a verdict or hangs. Produces a friction summary naming the conflicts that mattered.

### 7.9 Stage 10 — Experiment plan

Sensitivity output, filtered to `founder_asserted` parameters, ranked by output sensitivity, mapped to experiment templates, each with a pre-registered kill criterion, cost, and duration.

### 7.10 Stage 11–12 — Ledger version and return visit

Version 1 snapshot is written. Weeks later the founder logs a result against an experiment. The affected assumption's status changes mechanically against the pre-registered criterion; affected evidence and model parameters update; economics re-runs; the verdict is recomputed; version 2 is written with a computed diff.

The return visit UI shows the **diff**, not a new report:

> `pricing_wtp` moved **uncertain → refuted** because 3/20 pre-paid against a criterion of ≥4/20. This moved `price_monthly` from `founder_asserted ₹499` to `evidence_backed ₹249`, which moved the break-even delivery cost from ₹38 to ₹19. Verdict changed **PROCEED → PIVOT**.

---

## 8. Feature specifications

| ID | Feature | Priority | Acceptance criteria |
|---|---|---|---|
| **F1** | Magic-link auth | P0 | Email → link → session. No password field exists anywhere in the product. Session persists ≥30 days. |
| **F2** | Projects dashboard | P0 | Lists user's projects with last verdict, Evidence Confidence, version count, last activity. Opening a project restores full ledger state. |
| **F3** | Pitch intake + artifacts | P0 | Text pitch required; landing page URL, PDF/PPTX deck, repo URL optional. Artifacts extracted to text and stored. |
| **F4** | Archetype detection + override | P0 | Six archetypes, confidence shown, user-overridable, selects checklist. |
| **F5** | Assumption extraction + hearing | P0 | ≥8 assumptions on a typical pitch, each falsifiable and single-clause, scored on 3 axes, fully editable, run blocked until confirmed. |
| **F6** | Coverage gap report | P0 | Names every assumption class the pitch is silent on, before investigation begins. |
| **F7** | Five parallel investigators | P0 | All five run concurrently; every emitted claim has a fetched, resolvable source URL; tier assigned; scope typed. |
| **F8** | Live boardroom | P0 | Five columns; a row insert appears in the correct column within 2s; page reload and reconnect preserve state. |
| **F9** | Dedup + conflict engine | P0 | Deterministic; same source twice never inflates confidence; four conflict kinds detected; scope gaps reported as gaps, not contradictions. |
| **F10** | Targeted cross-examination | P0 | Fires only on real conflict at `blocking`/`high`; one round; concession or new tier ≤2 evidence required; position deltas persisted. |
| **F11** | Executable economics | P0 | Typed template, parameter provenance, break-even solved numerically, tornado chart rendered, no LLM arithmetic anywhere. |
| **F12** | Verdict + Evidence Confidence + hung jury | P0 | Confidence decomposed and displayed with its formula; gate provably prevents PROCEED/STOP below threshold. |
| **F13** | Experiment plan | P0 | Top-k founder-asserted, highest-sensitivity parameters; each experiment has method, cost, duration, and a non-null pre-registered kill criterion. |
| **F14** | Living ledger + diff | P0 | Result logging; mechanical status update against criterion; affected-only re-run; immutable versions; rendered causal diff. |
| **F15** | Ledger export (PDF/MD) | P1 | Full case file with all citations, exportable. |
| **F16** | Conflict graph visualisation | P1 | React Flow graph: assumptions as nodes, conflicts as edges, chairs as sources. |
| **F17** | Run event log viewer | P1 | Append-only trace of every node, tool call, latency, token count — visible in-app. Replaces external observability. |
| **F18** | Read-only ledger share link | P2 | Token URL for investors/co-founders. |
| **F19** | Backtest harness | P1 | Runs Jury against 10 known outcomes, reports verdict accuracy. Demo and deck asset. |

---

## 9. Scoring model and verdict gating

The scoring model exists to make the numbers defensible. Every input is countable.

### 9.1 Source tier weights

| Tier | Description | Weight | Persistable |
|---|---|---|---|
| 1 | Live primary artifact — pricing page, regulator register, API docs, filing, Wayback snapshot, store listing | 1.00 | Yes |
| 2 | Structured third-party data — funding databases, review aggregates with counts, official statistics | 0.80 | Yes |
| 3 | Journalism, analyst writeups, company blog posts | 0.55 | Yes |
| 4 | Forum/community anecdote — Reddit, HN, Indie Hackers comment | 0.30 | Yes |
| 5 | Model prior / unsourced LLM assertion | 0.00 | **No — rejected at insert** |

### 9.2 Per-assumption evidence strength

For assumption `a`, over deduplicated evidence items `i`:

```
support(a)  = Σ  tier_weight(i) × confidence(i)   for direction = supports
refute(a)   = Σ  tier_weight(i) × confidence(i)   for direction = refutes
raw(a)      = support(a) − refute(a)
strength(a) = tanh( |raw(a)| / 2 )        → 0..1, diminishing returns
```

Independent corroboration raises strength because dedup (P10) guarantees distinct sources. Status is then assigned:

| Condition | Status |
|---|---|
| no evidence items | `no_evidence` |
| `strength < 0.35` | `uncertain` |
| `raw > 0` and `strength ≥ 0.35` | `supported` |
| `raw < 0` and `strength ≥ 0.35` | `refuted` |
| unresolved conflict present | `contested` |

### 9.3 Evidence Confidence (0–100)

Four countable components, published weights:

```
coverage        = Σ crit_weight(c) · covered(c) / Σ crit_weight(c)
                  over assumption_classes c of the archetype
                  covered(c) = 1 if ≥1 assumption in c has ≥1 evidence item

mean_strength   = mean( strength(a) ) over assumptions where criticality ∈ {blocking, high}

contradiction   = unresolved_conflicts / max(1, investigated_critical_assumptions)

open_critical   = critical assumptions with status ∈ {no_evidence, uncertain}
                  / max(1, total critical assumptions)

EvidenceConfidence = 100 × (
      0.30 · coverage
    + 0.30 · mean_strength
    + 0.20 · (1 − min(1, contradiction))
    + 0.20 · (1 − open_critical)
)
```

The UI always displays the four components alongside the total. A number with a visible decomposition is defensible; a number without one is not.

### 9.4 The verdict gate

The Jury's decision is **separate** from Evidence Confidence, and is gated by it.

```
IF coverage < 0.70
   OR any assumption with criticality = 'blocking' has status ∈ {no_evidence, uncertain}
   OR EvidenceConfidence < 45
THEN verdict = HUNG_JURY        # PROCEED and STOP are structurally unreachable
```

Otherwise:

| Condition | Verdict |
|---|---|
| ≥1 `blocking` assumption `refuted` **and** no viable adjacent configuration found | `STOP` |
| ≥1 `blocking` or `high` assumption `refuted` **but** sensitivity/adjacency analysis identifies a configuration where the model is viable | `PIVOT` |
| All `blocking` assumptions `supported`, economics viable at evidence-backed parameters, no unresolved critical conflicts | `PROCEED` |

A `HUNG_JURY` always ships with the three cheapest experiments that would break the deadlock, selected by §16.5.

### 9.5 Why two numbers and not one

Evidence Confidence answers "how much do we know?" The verdict answers "what should you do?" They are deliberately decoupled: a STOP on thin evidence is as irresponsible as a PROCEED on thin evidence, and the gate makes that impossible to express.

---

## 10. System architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CLIENT — Next.js 15 on Vercel                                          │
│  Login · Dashboard · Pitch · Hearing · Boardroom · Conflict graph       │
│  Economics · Verdict · Experiments · Ledger diff · Export               │
└───────┬──────────────────────────────┬──────────────────────────────────┘
        │ supabase-js (auth, reads)    │ REST (run control)
        │ Realtime subscribe           │
        ▼                              ▼
┌────────────────────────┐   ┌──────────────────────────────────────────┐
│ SUPABASE               │   │  ORCHESTRATOR — FastAPI + LangGraph      │
│  · Auth (magic link)   │   │  on Google Cloud Run (60-min timeout)    │
│  · Postgres + pgvector │◄──┤                                          │
│  · Realtime (CDC)      │   │  Nodes:                                  │
│  · Storage (artifacts) │   │   archetype → extract → [interrupt]      │
│  · RLS on every table  │   │   → Send fan-out ×5 → dedup → conflict   │
└────────────────────────┘   │   → [conditional] cross-exam → economics │
                             │   → jury → experiments → version         │
                             │  Checkpointer: Postgres (resumable)      │
                             └───┬───────────┬────────────┬─────────────┘
                                 │           │            │
                ┌────────────────┘           │            └──────────────┐
                ▼                            ▼                           ▼
   ┌────────────────────────┐  ┌──────────────────────┐   ┌──────────────────────┐
   │ LLM GATEWAY (LiteLLM)  │  │ RETRIEVAL LAYER      │   │ UPSTASH REDIS        │
   │  → Groq only           │  │ Brave · Tavily · Exa │   │ · search cache       │
   │  model fallback chain  │  │ Reddit · HN Algolia  │   │ · fetch dedup        │
   │  retry · budget · JSON │  │ Play Store · Wayback │   │ · embedding cache    │
   │  repair loop           │  │ EDGAR · PH GraphQL   │   │ · token buckets      │
   └────────────────────────┘  └──────────┬───────────┘   │ · node idempotency   │
                                          ▼               └──────────────────────┘
                             ┌──────────────────────────┐
                             │ FETCH / EXTRACT TIERS    │
                             │ trafilatura → Jina Rdr   │
                             │ → Playwright (side svc)  │
                             └──────────┬───────────────┘
                                        ▼
   ┌────────────────────────┐  ┌──────────────────────┐   ┌──────────────────────┐
   │ QDRANT CLOUD           │  │ EMBEDDINGS           │   │ ECONOMICS ENGINE     │
   │ precedent corpus       │  │ fastembed (local)     │   │ typed templates +    │
   │ hybrid dense+sparse    │  │ bge-small-en-v1.5     │   │ numpy / scipy        │
   │ payload filters        │  │ no API key needed     │   │ trusted code only    │
   └────────────────────────┘  └──────────────────────┘   └──────────────────────┘
```

### 10.1 Why orchestration cannot live in a request handler

A run is minutes long, fans out five ways, conditionally branches, and pauses twice for human input — once at the assumption hearing, once for weeks at the return visit. That is a durable state machine with human-in-the-loop interrupts, not a web request. LangGraph with a Postgres checkpointer gives conditional edges, `Send` fan-out, and `interrupt()`/resume as first-class primitives, and survives an instance dying mid-run.

### 10.2 Why the database is the streaming layer

Server-sent events require a sticky connection to a scale-to-zero container and lose state on reconnect. Supabase Realtime subscribes to `evidence_items WHERE run_id = ?`, survives reconnects and reloads, and lets a founder reopen a half-finished run three weeks later. It also makes P3 structural rather than aspirational: there is no way to render a chair speaking without a ledger row existing.

SSE is retained for exactly one thing — token-level streaming of cross-examination prose, which is transient and not persisted as evidence.

---

## 11. Technology stack and rejected alternatives

### 11.1 Final stack

| Layer | Choice | Free tier | Key needed |
|---|---|---|---|
| Orchestration | LangGraph (OSS) + Postgres checkpointer | Free | No |
| Backend | FastAPI on Google Cloud Run | Always-free tier, 60-min timeout, scale-to-zero | GCP account |
| Database | Supabase Postgres | 500 MB, 2 projects | Yes (free) |
| Per-run vectors | pgvector (same Postgres) | Included | No |
| Precedent corpus | Qdrant Cloud | 1 GB free forever | Yes (free) |
| Realtime | Supabase Realtime | Included | Same key |
| Auth | Supabase Auth — magic link only | Included | Same key |
| Storage | Supabase Storage | 1 GB | Same key |
| Cache / rate limit | Upstash Redis | 500k cmd/mo, 256 MB | Yes (free) |
| LLM gateway | LiteLLM (OSS) | Free | No |
| LLM provider | **Groq** (sole provider) | Generous free tier, very high tok/s | Yes (free) |
| Embeddings | fastembed `bge-small-en-v1.5`, local | Free | No |
| Search | Brave Search API | 2k queries/mo | Yes (free) |
| Agentic search | Tavily | ~1k credits/mo | Yes (free) |
| Find-similar | Exa | Trial credits | Yes (free) |
| Community data | Reddit OAuth | Free | Yes (free) |
| Community data | HN Algolia API | Unlimited, keyless | **No** |
| Store data | `google-play-scraper` | Free | No |
| Launch data | Product Hunt GraphQL | Free | Yes (free) |
| Death verification | Wayback CDX API | Free, keyless | **No** |
| Filings | SEC EDGAR | Free | No |
| Extraction | trafilatura → Jina Reader → Playwright | Free / free / free | No |
| Economics | numpy + scipy (`brentq`) | Free | No |
| Frontend | Next.js 15 + Tailwind + shadcn/ui on Vercel | Hobby | No |
| Graphs | React Flow + Recharts | Free | No |
| Export | ReportLab | Free | No |
| Run tracing | **In-app `run_events` table** | Included | No |

### 11.2 Rejected alternatives — the decisions that matter

| # | Decision | Chosen | Rejected | Why |
|---|---|---|---|---|
| 1 | Primary database | **Supabase Postgres** | **CockroachDB** | Cockroach buys horizontal scale and multi-region survivability; neither is a requirement. The cost is real: no `LISTEN/NOTIFY`, weaker vector indexing than pgvector, serializable-only isolation forcing retry logic in every write path, and no bundled Realtime/Auth/Storage. You would add three services to replace what Supabase bundles free. Rejected on requirements, not quality. |
| | | | **Neon** | Excellent Postgres with branching and pgvector, but no realtime, auth, or storage. Would require Pusher + Clerk + S3. Supabase collapses four decisions into one. |
| | | | **MongoDB Atlas** | The ledger is a foreign-key graph with immutability and versioning requirements. Document modelling fights all three. |
| 2 | Orchestration | **LangGraph + Postgres checkpointer** | **Temporal** | Correct at real scale, wrong here: heavy self-host, worker/activity model to fight, no agent-native primitives. |
| | | | **Inngest / Trigger.dev** | Good durable-step platforms, but they would sit alongside LangGraph rather than replace it. Two orchestrators is one too many. |
| | | | **Celery / BullMQ** | Job queues, not state machines. Checkpointing, conditional routing and resume would all be hand-rolled. |
| 3 | Vector store | **pgvector primary + Qdrant for precedent** | Qdrant for everything | Per-run chunks are a few thousand vectors with a hard consistency requirement: an embedding must never outlive the evidence row it cites. Same transaction, same DB, `ON DELETE CASCADE`. Qdrant earns its place only for the genuinely different second workload — a long-lived cross-run postmortem corpus needing hybrid sparse+dense search and payload filtering. Two stores because there are two workloads. |
| | | | pgvector for everything | Workable, but hybrid BM25+dense and filtered-ANN tuning would be hand-built. |
| 4 | Economics engine | **Typed templates + trusted solver** | **LLM writes Python → sandbox (E2B/Daytona)** | Highest-leverage decision in this document. Per-archetype templates with the LLM filling a *validated schema* instead of authoring code gives: reproducible, diffable results across runs; a `provenance` field per parameter so sensitivity can mechanically nominate the next experiment; and elimination of the entire untrusted-code-execution surface. Sandbox removed from the stack entirely per scope decision. |
| 5 | Streaming | **Supabase Realtime on ledger tables** | SSE from FastAPI | SSE needs a sticky connection to a scale-to-zero container and loses state on reconnect. Realtime survives reloads and multi-week gaps, and structurally prevents UI/ledger drift. SSE retained only for transient cross-exam tokens. |
| | | | Pusher / Ably | Fine free tiers, but a fourth service to do something already owned. |
| 6 | Backend host | **Cloud Run** | Vercel / Netlify functions | 10–60 s timeouts kill a multi-minute run. Cloud Run allows 60 minutes, scales to zero, real always-free tier. |
| | | | Render free tier | Spins down after 15 min idle — acceptable, kept as zero-config fallback because checkpointing makes runs resumable. |
| | | | Modal | Strong alternative; pick it over Cloud Run if you prefer infra-as-Python-decorators to a Dockerfile. |
| 7 | LLM provider | **Groq, single provider** | Multi-provider (Claude + Gemini split) | Scope decision. Consequences are real and mitigated in §15: Groq has no embeddings API (so local fastembed becomes load-bearing, not optional), and open-weight models are weaker at strict structured output than frontier models (so a schema-validation and repair loop becomes mandatory). |
| 8 | Model access | **LiteLLM gateway retained** | Direct Groq SDK | Even single-provider, the gateway earns its place: model-level fallback within Groq, unified retry/backoff, budget caps, and a one-line provider swap if Groq throttles during judging. |
| 9 | Tracing | **In-app `run_events` table** | **Langfuse / LangSmith** | External observability removed per scope decision. Replacement is a first-class append-only trace table: one row per node entry/exit, tool call, latency, token count, and error. Costs one table, removes a service, and doubles as a demo asset — showing judges the trace inside the product proves the pipeline is real. |
| 10 | Embeddings | **Local fastembed** | Hosted embedding API | Highest-volume call in the system. Local removes an entire class of rate-limit and network failure, and Groq does not serve embeddings. |
| 11 | Search | **Brave + Tavily + Exa, routed per chair** | One universal search tool | Precedent needs semantic find-similar (Exa); Market needs an independent index and direct page fetches (Brave); Customer needs domain APIs. Neither substitutes for the other. |
| 12 | Auth | **Supabase magic link only** | Password auth / OAuth providers | Scope decision. Also correct: no password reset flow, no credential storage, no password UI, and the whole surface is one table and one callback route. |

---

## 12. Data model

Postgres. Every table carries `user_id` and is protected by row-level security. `evidence_items` is insert-only.

```sql
-- ========== identity & ownership ==========
-- auth.users is managed by Supabase Auth

create table profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  email         text not null,
  created_at    timestamptz default now()
);

create table projects (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null,
  archetype     text,                    -- marketplace | subscription_saas | d2c | services | ad_consumer | hardware
  target_scope  jsonb not null,          -- {geo, segment, tier, period} -- the scope that matters
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create table runs (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  user_id       uuid not null references auth.users(id) on delete cascade,
  kind          text not null,           -- initial | return_visit | pivot_check
  status        text not null,            -- pending | hearing | investigating | cross_exam | deciding | complete | failed
  thread_id     text not null,            -- LangGraph checkpoint thread
  started_at    timestamptz default now(),
  completed_at  timestamptz
);

create table pitches (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  body          text not null,
  artifacts     jsonb default '[]',      -- [{kind: deck|landing|repo, url, storage_path}]
  created_at    timestamptz default now()
);

-- ========== the coverage denominator (hand-seeded, never LLM-generated) ==========
create table assumption_classes (
  key           text primary key,        -- e.g. 'marketplace.supply_liquidity'
  archetype     text not null,
  label         text not null,
  question      text not null,           -- the question this class must answer
  crit_weight   numeric not null         -- 1.0 blocking, 0.6 high, 0.3 medium
);

-- ========== assumptions: propositions, not evidence ==========
create table assumptions (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid references runs(id),          -- run that introduced it
  class_key     text references assumption_classes(key),
  statement     text not null,                     -- single falsifiable clause
  origin        text not null,                     -- founder | discovered
  discovered_by text,                              -- chair, when origin = discovered
  criticality   text not null,                     -- blocking | high | medium | low
  uncertainty   text not null,                     -- unknown | uncertain | likely | established
  falsifiability text not null,                    -- testable_now | testable_costly | untestable
  asserted_variable text,                          -- for founder assertions with a number
  asserted_value    numeric,
  asserted_unit     text,
  status        text not null default 'no_evidence', -- no_evidence|uncertain|supported|refuted|contested
  strength      numeric default 0,
  superseded_by uuid references assumptions(id),
  created_at    timestamptz default now()
);

-- ========== sources ==========
create table sources (
  id            uuid primary key default gen_random_uuid(),
  canonical_url text not null,
  domain        text not null,
  tier          int  not null check (tier between 1 and 4),   -- tier 5 cannot exist
  title         text,
  retrieved_at  timestamptz not null default now(),
  http_status   int  not null,
  storage_path  text,                    -- extracted text in Supabase Storage
  unique (canonical_url)
);

-- ========== evidence: insert-only, source-backed ==========
create table evidence_items (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid not null references runs(id),
  assumption_id uuid not null references assumptions(id) on delete cascade,
  source_id     uuid not null references sources(id),
  chair         text not null,           -- market|customer|precedent|dependencies|economics
  direction     text not null,           -- supports | refutes
  variable      text,
  value_num     numeric,
  value_min     numeric,
  value_max     numeric,
  unit          text,
  scope_geo     text not null,           -- enum
  scope_segment text not null,           -- enum
  scope_tier    text,                    -- enum
  scope_period  text,
  confidence    numeric not null check (confidence between 0 and 1),
  excerpt       text not null,           -- verbatim, <= 240 chars
  dedup_hash    text not null,
  superseded_by uuid references evidence_items(id),
  created_at    timestamptz default now(),
  unique (project_id, dedup_hash)        -- P10: same source twice never inflates confidence
);

create index on evidence_items (assumption_id);
create index on evidence_items (run_id, chair);

-- ========== retrieval ==========
create table source_chunks (
  id            uuid primary key default gen_random_uuid(),
  source_id     uuid not null references sources(id) on delete cascade,
  chunk_index   int not null,
  content       text not null,
  embedding     vector(384)              -- bge-small-en-v1.5
);
create index on source_chunks using hnsw (embedding vector_cosine_ops);

-- ========== conflicts ==========
create table conflicts (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid not null references runs(id),
  assumption_id uuid not null references assumptions(id) on delete cascade,
  kind          text not null,           -- founder_vs_world | chair_vs_chair | no_evidence | scope_gap
  left_ref      jsonb not null,          -- {type: evidence|assumption, id}
  right_ref     jsonb,
  rule          text not null,           -- R1..R5
  severity      text not null,
  status        text not null default 'open', -- open | resolved | conceded | unresolvable
  resolution    text,
  created_at    timestamptz default now()
);

create table position_deltas (
  id            uuid primary key default gen_random_uuid(),
  conflict_id   uuid not null references conflicts(id) on delete cascade,
  chair         text not null,
  before        text not null,
  after         text not null,
  reason        text not null,
  new_evidence_id uuid references evidence_items(id)
);

-- ========== economics ==========
create table model_runs (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  run_id        uuid not null references runs(id),
  template_key  text not null,           -- marketplace_v1 | saas_v1 | d2c_v1 | services_v1
  parameters    jsonb not null,          -- {key: {value, unit, provenance, source_id?, assumption_id?}}
  outputs       jsonb not null,          -- {contribution_margin, payback_months, ltv_cac, ...}
  breakpoints   jsonb not null,          -- [{variable, threshold, direction, unit}]
  sensitivity   jsonb not null,          -- [{variable, elasticity, provenance}] ranked desc
  viable        boolean not null,
  created_at    timestamptz default now()
);

-- ========== experiments ==========
create table experiments (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references projects(id) on delete cascade,
  assumption_id   uuid not null references assumptions(id) on delete cascade,
  target_variable text,
  method          text not null,         -- fake_door | presale | interview_script | supplier_quote | landing_ctr | ...
  instructions    text not null,
  kill_criterion  text not null,         -- P9: non-null required before export
  criterion_spec  jsonb not null,        -- {metric, comparator, threshold, n} -- machine-evaluable
  est_cost        numeric,
  est_days        int,
  priority        int not null,
  status          text not null default 'proposed', -- proposed | running | passed | failed | abandoned
  result_value    numeric,
  result_notes    text,
  logged_at       timestamptz
);

-- ========== verdicts & versions ==========
create table verdicts (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references runs(id) on delete cascade,
  project_id    uuid not null references projects(id) on delete cascade,
  decision      text not null,           -- PROCEED | PIVOT | STOP | HUNG_JURY
  evidence_confidence numeric not null,
  components    jsonb not null,          -- {coverage, mean_strength, contradiction, open_critical}
  gate_triggered text,                   -- which gate condition fired, if any
  friction      jsonb not null,          -- conflicts that mattered
  rationale     text not null,
  created_at    timestamptz default now()
);

create table ledger_versions (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  version       int not null,
  run_id        uuid not null references runs(id),
  snapshot      jsonb not null,          -- full immutable ledger state
  diff          jsonb not null,          -- computed causal delta vs previous version
  created_at    timestamptz default now(),
  unique (project_id, version)
);

-- ========== in-app tracing (replaces external observability) ==========
create table run_events (
  id            bigserial primary key,
  run_id        uuid not null references runs(id) on delete cascade,
  ts            timestamptz default now(),
  node          text not null,
  event         text not null,           -- node_start|node_end|llm_call|tool_call|fetch|error|interrupt
  detail        jsonb,                   -- {model, prompt_tokens, completion_tokens, url, ms, error}
  latency_ms    int
);
create index on run_events (run_id, ts);
```

### 12.1 The three constraints that carry product integrity

1. **`evidence_items` is insert-only.** Corrections happen via `superseded_by`. This is what makes the audit trail real, and retrofitting it later is a rewrite.
2. **`unique (project_id, dedup_hash)`** where `dedup_hash = sha256(canonical_url ‖ variable ‖ scope_geo ‖ scope_segment ‖ scope_tier)`. Two chairs finding the same pricing page cannot inflate confidence twice.
3. **Scope columns are enumerated, not free text.** A free-text scope is uncomparable, and the conflict engine would flag ₹149 US-SMB against ₹500 IN-enterprise as a contradiction. Enumerated scope makes overlap computable and lets the system report a **scope gap** — evidence exists, but none of it covers your target — which is its own valuable finding.

### 12.2 Scope enumerations

| Field | Values |
|---|---|
| `scope_geo` | `IN`, `US`, `EU`, `UK`, `SEA`, `MENA`, `LATAM`, `GLOBAL` |
| `scope_segment` | `consumer`, `prosumer`, `smb`, `mid_market`, `enterprise`, `public_sector` |
| `scope_tier` | `free`, `entry`, `mid`, `premium`, `enterprise` |
| `scope_period` | `YYYY` or `YYYY-Qn` |

Overlap rule: two scopes overlap if every populated field either matches or one side is a superset (`GLOBAL` supersets any geo; a null tier supersets all tiers).

### 12.3 Seeded assumption classes (excerpt)

**Marketplace** — all `crit_weight` shown:

| Key | Question | Weight |
|---|---|---|
| `marketplace.demand_exists` | Do buyers actively look for this today? | 1.0 |
| `marketplace.supply_liquidity` | Will enough supply join and stay? | 1.0 |
| `marketplace.take_rate_tolerance` | Will either side accept the commission? | 1.0 |
| `marketplace.unit_economics` | Does revenue per transaction exceed delivered cost? | 1.0 |
| `marketplace.channel_cost` | Can both sides be acquired affordably? | 0.6 |
| `marketplace.frequency` | Is purchase frequency high enough to matter? | 0.6 |
| `marketplace.disintermediation` | What stops both sides transacting off-platform? | 0.6 |
| `marketplace.ops_feasibility` | Can fulfilment/trust/dispute be operated at this scale? | 0.6 |
| `marketplace.regulatory` | Any licence, tax, or compliance requirement? | 1.0 |
| `marketplace.incumbency` | Is the space already served or already a graveyard? | 0.3 |

**Subscription SaaS:**

| Key | Question | Weight |
|---|---|---|
| `saas.pain_severity` | Is the pain acute enough to pay for? | 1.0 |
| `saas.wtp_above_cost` | Does WTP exceed delivered cost per account? | 1.0 |
| `saas.retention` | Will accounts stay long enough to repay acquisition? | 1.0 |
| `saas.channel_cost` | Is CAC recoverable within an acceptable payback? | 1.0 |
| `saas.buyer_identity` | Is there a budget holder who can actually buy? | 0.6 |
| `saas.switching_cost` | What makes them leave the current solution? | 0.6 |
| `saas.dependency_risk` | Do required third parties permit this at viable cost? | 0.6 |
| `saas.data_compliance` | Any data/privacy/regulatory constraint? | 0.6 |
| `saas.incumbency` | Is the category already won or already a graveyard? | 0.3 |
| `saas.expansion` | Is there an observable adjacency for expansion? | 0.3 |

The remaining four archetypes (`d2c`, `services`, `ad_consumer`, `hardware`) are seeded identically — eight to ten classes each, weights assigned by hand. **This is an afternoon of work and it is the only thing standing between a defensible coverage score and a self-graded one.**

---

## 13. API surface

FastAPI on Cloud Run. All routes require a Supabase JWT in `Authorization: Bearer`. The orchestrator validates the JWT and uses the user's ID for all writes, so RLS applies to service-side writes too.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/projects` | Create project from a pitch; returns detected archetype + confidence |
| `GET` | `/projects` | List the user's projects with last verdict and confidence |
| `GET` | `/projects/{id}` | Full current ledger state |
| `PATCH` | `/projects/{id}` | Override archetype or target scope |
| `POST` | `/projects/{id}/artifacts` | Upload deck / register landing page or repo URL |
| `POST` | `/projects/{id}/runs` | Start a run (`kind = initial \| return_visit \| pivot_check`) |
| `GET` | `/runs/{id}` | Run status + current node |
| `GET` | `/runs/{id}/events` | `run_events` trace (F17) |
| `POST` | `/runs/{id}/hearing/confirm` | Resume from the assumption-hearing interrupt with edits |
| `POST` | `/runs/{id}/cancel` | Cancel; checkpoint retained |
| `GET` | `/projects/{id}/assumptions` | Assumption graph with status and strength |
| `GET` | `/projects/{id}/evidence` | Evidence ledger, filterable by assumption / chair / tier |
| `GET` | `/projects/{id}/conflicts` | Conflicts + position deltas |
| `GET` | `/projects/{id}/economics` | Latest model run: parameters, breakpoints, sensitivity |
| `GET` | `/projects/{id}/verdict` | Latest verdict with confidence components |
| `GET` | `/projects/{id}/experiments` | Experiment plan |
| `POST` | `/experiments/{id}/result` | Log a result; evaluates against `criterion_spec`; triggers affected-only re-run |
| `GET` | `/projects/{id}/versions` | Version list |
| `GET` | `/projects/{id}/versions/{v}/diff` | Rendered causal diff |
| `POST` | `/projects/{id}/export` | Generate PDF/MD case file |
| `POST` | `/projects/{id}/share` | Create read-only token link (F18) |

Reads that the client can satisfy directly through `supabase-js` with RLS (assumptions, evidence, conflicts, verdicts, versions) should go direct, not through FastAPI. The orchestrator owns writes and run control only. This keeps the backend small and the Realtime path simple.

---

## 14. Authentication and persistence

### 14.1 Requirement

Passwordless email magic links via Supabase Auth. No passwords anywhere in the product. Every project, run, assumption, evidence item, conflict, model run, experiment, verdict and ledger version persists to the user's account so they can return weeks later and continue the same validation cycle.

### 14.2 Flow

```
/login
  └─ email input ──► supabase.auth.signInWithOtp({ email, options: { emailRedirectTo }})
                      └─ "Check your inbox" state (no password field rendered anywhere)

email link ──► /auth/callback
                 └─ exchangeCodeForSession()
                      ├─ upsert into profiles
                      └─ redirect ──► /projects (dashboard)

/projects
  ├─ [New project] ──► /projects/new (pitch intake)
  └─ [Project card] ──► /projects/{id} (restores full ledger, any version, any open run)
```

Four screens total for the entire auth and navigation surface: `/login`, `/auth/callback`, `/projects`, `/projects/{id}`.

### 14.3 Session handling

- Supabase SSR cookie-based sessions; middleware refreshes on each request.
- Refresh token rotation on; session lifetime 30 days so a three-week return visit does not require re-authentication.
- Unauthenticated access to any `/projects*` route redirects to `/login` with a `next` parameter.
- Magic-link rate limiting is handled by Supabase; a second Upstash token bucket caps requests per email per hour to protect the free email quota.

### 14.4 Row-level security

RLS is the persistence guarantee. Every table gets the same pattern:

```sql
alter table projects enable row level security;
create policy "own projects" on projects
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- child tables authorise through the project
alter table assumptions enable row level security;
create policy "own assumptions" on assumptions
  for all using (
    exists (select 1 from projects p
            where p.id = assumptions.project_id and p.user_id = auth.uid())
  );
-- repeat for: runs, pitches, evidence_items, sources(read-all), conflicts,
-- position_deltas, model_runs, experiments, verdicts, ledger_versions, run_events
```

`evidence_items` additionally denies `UPDATE` and `DELETE` to all roles including the service role, enforcing P6 at the database level rather than in application code.

`sources` is deliberately readable across users and deduplicated globally — a fetched pricing page is not private data, and sharing the cache reduces search quota burn. Nothing user-identifying is stored on it.

### 14.5 Explicitly out of scope

Passwords, password reset, OAuth providers, MFA, teams, roles, invitations, org accounts. None of these are required to prove the product, and each adds surface area that judges will not evaluate.

---

## 15. LLM layer

### 15.1 Configuration

Single provider: **Groq**, accessed through the **LiteLLM** gateway.

| Task | Model role | Rationale |
|---|---|---|
| Assumption extraction and classification | Large reasoning model | Needs to split clauses into single falsifiable propositions and assign three axes. Highest-quality task in the system. |
| Archetype detection | Small fast model | Six-way classification with confidence. Cheap. |
| Claim structuring from fetched page text | Small fast model, high volume | The dominant call count. Extracting typed claims from extracted text. |
| Scope typing | Small fast model | Mapping free text to the scope enums. |
| Cross-examination | Large reasoning model | The only genuinely adversarial reasoning task. |
| Jury rationale prose | Large reasoning model | The score and verdict are computed in code; the model only writes the explanation. |
| Experiment instructions | Mid model | Filling a template, not inventing method. |

Groq deprecates and renames models frequently. **Resolve actual model IDs in the Groq console at build time** and keep them in a single config map — do not hardcode them across the codebase. At time of writing the relevant candidates are the Llama 3.3 70B class for reasoning, the Llama 3.1 8B instant class for high-volume extraction, and the GPT-OSS 120B class as an alternative reasoning tier. Verify before relying on any of these names.

### 15.2 Why the gateway is retained despite a single provider

| Gateway function | Value with one provider |
|---|---|
| Model fallback chain | High — if the 70B tier throttles, fall back to the next tier within Groq rather than failing the run |
| Unified retry / backoff | High — one place to handle 429s across all seven call sites |
| Budget caps and token accounting | High — feeds `run_events` for in-app tracing |
| Provider swap | Insurance — if Groq is degraded during judging, one config line points at any other provider a judge supplies via env var |
| Prompt/response logging hook | Medium — writes to `run_events` |

### 15.3 Consequences of single-provider, and their mitigations

Two real costs follow from this decision, and both must be engineered around rather than hoped away.

**Groq serves no embeddings API.** Local `fastembed` is therefore load-bearing rather than optional. This is fine and arguably better — it is the highest-volume call in the system and running it locally removes an entire class of rate-limit and network failure — but it means the container must ship the model weights and a cold start pays the load cost once. Mitigation: bake weights into the image at build time; warm on container start; cache embeddings in Redis keyed by content hash.

**Open-weight models are weaker at strict structured output than frontier models.** Since every chair's output contract is a typed JSON record (§6.1), this is the single largest reliability risk in the build. Mitigations, all mandatory:

1. JSON mode enabled on every structured call.
2. Pydantic validation on every response, with the schema also embedded in the prompt.
3. A **repair loop**: on validation failure, re-prompt once with the validation error and the offending output attached.
4. On second failure, downgrade the task — split one extraction call into several narrower single-field calls, which small models handle far more reliably than one large nested object.
5. On third failure, drop the claim and write an `error` row to `run_events`. A dropped claim is acceptable; a malformed ledger row is not.
6. Never ask a model for a number that can be computed. All arithmetic goes through the economics engine (P8).

**Single point of failure.** If Groq is throttled or down mid-demo, the whole system stalls. Mitigations: aggressive Redis caching of all LLM responses keyed by prompt hash; pre-warmed cache for the demo pitch; documented `LLM_PROVIDER` / `LLM_API_KEY` env override so any judge can point the gateway elsewhere in seconds.

---

## 16. Engine specifications

### 16.1 Retrieval and extraction

Search routing per chair, with per-chair budgets:

| Chair | Providers | Query budget / run |
|---|---|---|
| Market | Brave (primary), Tavily | 8 |
| Customer | Reddit OAuth, HN Algolia, google-play-scraper, Brave | 8 |
| Precedent | Exa find-similar, Brave, Wayback CDX, Product Hunt | 10 |
| Dependencies | Brave, direct doc/registry fetch | 6 |
| Economics | Brave (benchmark lookups only) | 3 |

Fetch and extraction is tiered by cost:

1. **trafilatura** — local, free, handles most article and doc pages.
2. **Jina Reader** (`r.jina.ai/<url>`) — free, no key, good fallback for awkward markup.
3. **Playwright** — for JS-rendered pages, which is most modern pricing pages. Deployed as a **separate small Cloud Run service** so the main orchestrator image stays lean and cold-starts fast.

Every fetch is deduplicated in Redis by canonical URL with a 24-hour TTL. Canonicalisation strips tracking parameters, fragments, and trailing slashes before hashing.

### 16.2 Source tier assignment

Tier is assigned by **rule, not by model**:

| Rule | Tier |
|---|---|
| Domain matches a regulator, government register, or filing system | 1 |
| URL is a pricing/plans page on the vendor's own domain, fetched live | 1 |
| Wayback CDX snapshot record | 1 |
| App/Play store listing with metadata | 1 |
| API documentation page on the vendor's own domain | 1 |
| Known structured-data domains (funding databases, official statistics) | 2 |
| Review aggregate with a visible count | 2 |
| Known news/analyst domains | 3 |
| Vendor blog or marketing page | 3 |
| Reddit, HN, Indie Hackers, forum thread | 4 |
| Anything unresolvable | **rejected** |

A domain allowlist/tier map is seeded by hand and extended as needed. Unknown domains default to tier 3.

### 16.3 Conflict engine (deterministic, no LLM)

| Rule | Condition | Kind | Triggers cross-exam |
|---|---|---|---|
| **R1** | Same assumption has ≥1 `supports` and ≥1 `refutes`, both tier ≤ 2, overlapping scope | `chair_vs_chair` | Yes, if criticality ∈ {blocking, high} |
| **R2** | Two evidence items on the same `variable`, overlapping scope, non-overlapping value ranges beyond a ±10% tolerance band | `chair_vs_chair` | Yes, same condition |
| **R3** | Founder-origin assumption with `asserted_value` V, and an evidence item on the same variable with overlapping scope where `abs(V − E) / E > 0.25` | `founder_vs_world` | **Always** |
| **R4** | Critical assumption with zero evidence items after investigation completes | `no_evidence` | No — reported, and feeds the gate |
| **R5** | Evidence exists for an assumption but none of it overlaps the project's `target_scope` | `scope_gap` | No — reported as a gap |

R3 is the rule that earns the product its existence. The founder's pitch is a set of claims in the same system as everything else, and it is expected to lose.

Sequence: dedup by `dedup_hash` first, then apply R1–R5 as SQL, then optionally use pgvector similarity to catch near-duplicate statements of the same variable under different names.

### 16.4 Cross-examination protocol

- Triggered only per §16.3.
- One round. Maximum two chairs per conflict. Hard cap of five conflicts cross-examined per run, selected by criticality then severity.
- Each participating chair receives: the conflict, both claims with their sources and excerpts, and its own prior position. It must return either a new tier-1 or tier-2 evidence item that resolves the conflict, or an explicit concession.
- Outcomes written to `conflicts.status` and `position_deltas`.
- Unresolved conflicts remain `open` and increase the `contradiction` term in §9.3, which pushes toward `HUNG_JURY`. This is correct behaviour: unresolved disagreement is a reason to know less, not a reason to pick a side.

### 16.5 Economics engine

**Templates, not generated code.** One typed template per archetype. The LLM fills a validated parameter schema; it never authors or executes code.

Marketplace template parameters:

| Parameter | Unit | Typical provenance source |
|---|---|---|
| `aov` | currency | Market (competitor pricing), or founder |
| `take_rate` | fraction | Founder assertion, tested by Customer WTP evidence |
| `delivery_cost` | currency/txn | Dependencies (supplier/logistics pricing) |
| `payment_fee` | fraction | Dependencies (gateway pricing page) |
| `cac_buyer` / `cac_supplier` | currency | Market or Customer benchmark evidence |
| `txn_per_buyer_month` | count | Customer evidence or founder |
| `buyer_churn_monthly` | fraction | Customer evidence or founder |
| `support_cost_per_txn` | currency | Founder |
| `fixed_monthly` | currency | Founder |

Every parameter carries `provenance ∈ {evidence_backed, founder_asserted}` and, when evidence-backed, a `source_id`.

Computation:

- Contribution margin per transaction, LTV, LTV/CAC, payback period, monthly break-even volume.
- **Breakpoints** solved numerically with `scipy.optimize.brentq` over each parameter's plausible range, holding others fixed: the exact value at which contribution margin crosses zero or LTV/CAC crosses 1.0. Output is a sentence like *"the business becomes loss-making above ₹38 delivery cost."*
- **Sensitivity** by one-at-a-time elasticity: perturb each parameter ±20% and record the proportional change in the primary output. Ranked descending. Rendered as a tornado chart.
- Monte Carlo is explicitly **out of scope**; a deterministic breakpoint solve plus elasticity ranking delivers the same decision value at a fraction of the build cost.

### 16.6 Experiment generator

This is the join that makes the four pillars one machine instead of four features:

```
sensitivity ranking
  → filter provenance = 'founder_asserted'
      → the highest-sensitivity parameter that is still a guess
          → is, by construction, the highest-value thing to go learn
              → becomes experiment #1
```

Variable-to-method mapping:

| Target variable class | Method | Typical cost | Typical duration |
|---|---|---|---|
| Willingness to pay / price | `presale` or `fake_door` with a real checkout | Landing page + ad spend | 5–10 days |
| Demand existence | `landing_ctr` against a paid or organic channel | Small ad budget | 5–7 days |
| Delivery / unit cost | `supplier_quote` — contact N providers for written quotes | Free | 3–5 days |
| Take-rate tolerance | `interview_script` with a pre-registered acceptance count | Free | 5–7 days |
| Channel cost / CAC | `landing_ctr` + measured cost per signup | Ad budget | 7–14 days |
| Regulatory permissibility | `registry_check` or written enquiry to the regulator | Free | 7–21 days |
| Retention | Not testable in 30 days — substitute a documented proxy and flag the substitution explicitly | — | — |

Every generated experiment carries a machine-evaluable `criterion_spec`:

```json
{ "metric": "prepay_count", "comparator": ">=", "threshold": 4, "n": 20 }
```

Pre-registering the threshold is what stops the founder returning with an ambiguous result and rationalising it, and it makes the ledger update mechanical rather than another model judgement.

### 16.7 Precedent engine

The weakest retrieval in the system by a wide margin, because dead companies are badly indexed and search surfaces launch announcements rather than postmortems. Design accordingly.

- **Widen from failures to outcomes.** Successes are evidence about which conditions were load-bearing. And "nobody has attempted this" is itself a finding, usually an unflattering one.
- **Source list:** Exa find-similar seeded from the pitch; Failory and autopsy.io postmortem collections; r/startups and r/SaaS postmortem threads; Indie Hackers; Product Hunt launches; HN "Show HN" threads with no follow-up; Play Store listings with a last-update date years old.
- **Death verification via Wayback CDX.** Free, keyless, and it converts "this company seems gone" into a citable snapshot date plus a dead live URL. This is the single highest-value retrieval trick in the product and it is the answer to "how do I know you didn't invent this company."
- **Anti-hallucination rule, enforced in code not prompt:** a precedent claim is rejected at insert unless it carries a resolvable source URL that was actually fetched and returned a 2xx. Verify before persist.
- **Qdrant precedent corpus:** every verified precedent is embedded into a durable collection with payload filters on `archetype`, `industry`, `outcome`, `cause_category`, `year`, `geo`. The corpus grows across users and runs, so precedent quality improves with usage. This is the only genuinely durable asset the product accumulates.

### 16.8 Ledger diff engine

On each new version, compute a typed diff against the previous snapshot:

| Diff type | Rendered as |
|---|---|
| `assumption_status_change` | `uncertain → refuted`, with the triggering evidence or experiment result |
| `evidence_added` | Count by chair and tier |
| `assumption_discovered` | New assumptions surfaced during investigation |
| `conflict_resolved` | Conflict, resolution, conceding chair |
| `parameter_provenance_change` | `founder_asserted → evidence_backed`, with the new value |
| `breakpoint_moved` | Old threshold → new threshold |
| `confidence_change` | Old → new, with which of the four components moved |
| `verdict_change` | `PROCEED → PIVOT`, with the causal chain |

The return-visit screen renders the causal chain as a single sentence path, not a list of unrelated changes. This is the cheapest-to-build and strongest demo beat in the product.

---

## 17. Non-functional requirements

### 17.1 Performance targets

| Metric | Target |
|---|---|
| Assumption hearing ready | ≤ 45 s p50 from pitch submission |
| Full investigation wall clock | ≤ 5 min p50, ≤ 9 min p95 |
| First evidence row visible in boardroom | ≤ 20 s from hearing confirmation |
| Realtime row to UI latency | ≤ 2 s |
| Cross-examination round | ≤ 60 s |
| Economics solve | ≤ 3 s |
| Return-visit affected-only re-run | ≤ 90 s |
| Cold start (main service) | ≤ 8 s |

### 17.2 Budgets and quota discipline

| Resource | Per-run budget | Guard |
|---|---|---|
| Search queries | 35 across all chairs | Redis token bucket per provider |
| Page fetches | 60 | Canonical-URL dedup cache, 24 h TTL |
| Playwright fetches | 8 | Separate service, only for known-JS domains |
| LLM calls | ~120 | Prompt-hash response cache; budget cap in gateway |
| Embeddings | ~3000 chunks | Local; content-hash cache |
| Qdrant writes | verified precedents only | — |

### 17.3 Idempotency and resumability

- Every LangGraph node writes an idempotency key to Redis before side effects; a replayed node short-circuits.
- Every fetch is idempotent via the canonical-URL cache.
- Postgres checkpointer means a container death resumes from the last completed node.
- `POST /experiments/{id}/result` is idempotent on `(experiment_id, result_value)`.

### 17.4 Security and privacy

- RLS on every user-owned table; `evidence_items` denies UPDATE/DELETE to all roles.
- Secrets in Cloud Run secret env vars and Vercel environment variables. Nothing in the repo. `.env.example` committed with key names only.
- JWT validated server-side on every orchestrator route.
- Artifact uploads scanned for size and MIME type; stored in a private Storage bucket with signed-URL access.
- Outbound fetches run through an allowlist-blocklist check; no fetching of `localhost`, private IP ranges, or cloud metadata endpoints (SSRF guard). This matters because target URLs are partly model-selected.
- Model-selected URLs are data, never instructions. Fetched page content is never interpreted as a directive to the system.
- No PII beyond email is stored. Pitches are user content and are never shared across accounts.

### 17.5 Cost ceiling

Target: **zero recurring cost** on free tiers for the hackathon and for judge evaluation. The only paid escalation risks are Cloud Run egress above the always-free allowance and search quota overrun; both are bounded by §17.2 budgets.

---

## 18. Failure modes and degradation

The system must degrade to "less evidence" rather than "crash." Every missing source becomes a documented absence, which is itself a valid ledger state.

| Failure | Detection | Degradation |
|---|---|---|
| Groq 429 / throttle | Gateway error | Fall back down the model chain; serve cached responses; retry with backoff; surface a banner, never a blank run |
| Groq down entirely | Repeated 5xx | Run pauses at checkpoint and resumes when available; `LLM_PROVIDER` env override documented for judges |
| Malformed JSON from model | Pydantic validation fails | Repair loop → field-split retry → drop claim + `run_events` error row |
| Search quota exhausted | Provider 429 | Switch provider within the chair; then serve from cache; then mark chair `partial` and reduce that chair's contribution, which lowers coverage and correctly pushes toward HUNG_JURY |
| Reddit OAuth throttle | 429 | 24 h cache by subreddit+query; degrade to HN Algolia, which is keyless and unlimited |
| Playwright service cold/failing | Timeout | Fall back to Jina Reader, then trafilatura; if all fail, no evidence row is written (P1) |
| Page fetch 403 / paywall | HTTP status | Claim rejected at insert; logged as a rejected source |
| LLM invents a company or a statistic | Pre-persist fetch verification returns non-2xx or the excerpt is absent from the extracted text | Claim rejected before insert. This check is the product's integrity guarantee and is non-optional |
| Cloud Run instance dies mid-run | Missing heartbeat | Postgres checkpoint resume; idempotent nodes |
| Supabase Realtime drops | Client detects | Client refetches on reconnect; state is in Postgres, not in the socket |
| Novel pitch genuinely has no evidence | Coverage below gate | `HUNG_JURY` with three cheapest experiments. Correct behaviour, and it must be presented as a feature rather than a bug |
| Free-tier email quota hit on magic links | Supabase error | Per-email Upstash rate limit upstream; clear user-facing message |

---

## 19. Evaluation and backtest

Almost nobody at a hackathon ships an evaluation of their own product's judgement. This is the cheapest credibility available and it belongs in the deck.

### 19.1 Verdict backtest

Ten real early-stage companies with known outcomes: five that succeeded, five that shut down. For each, reconstruct a pitch using **only information available at their seed stage**, and restrict retrieval to sources predating that date where feasible (Wayback makes this partly possible for pricing and competitor pages).

Reported metrics:

| Metric | Definition |
|---|---|
| Directional accuracy | Fraction where `PROCEED`/`PIVOT` aligned with survival and `STOP` aligned with shutdown |
| Hung-jury rate | Fraction where the system correctly declined to rule |
| Cause-of-death hit rate | For dead companies, whether the actual cause appeared as a `refuted` or `contested` assumption |

Cause-of-death hit rate is the most honest and most impressive of the three: it tests whether Jury found the right *reason*, not just the right *label*.

### 19.2 Component evals

| Component | Test | Pass bar |
|---|---|---|
| Assumption extraction | 20 pitches, human-labelled load-bearing assumptions | ≥80% recall on blocking assumptions |
| Source tier assignment | 100 labelled URLs | ≥95% correct, since it is rule-based |
| Conflict engine | Synthetic fixtures with known conflicts and known scope gaps | 100% — it is deterministic |
| Scope overlap | Fixture matrix over the enums | 100% |
| Hallucination guard | 50 fabricated company names injected into model output | 100% rejected at insert |
| Economics solver | Hand-computed fixtures | Exact agreement |
| Kill-criterion evaluation | Fixture results against `criterion_spec` | 100% |

Deterministic components must score 100%. That is the point of making them deterministic.

---

## 20. Build plan

Sequenced so that a working vertical slice exists early and every later day adds a demo beat rather than a dependency. The cut line marks what ships even if everything goes wrong.

| Phase | Work | Output |
|---|---|---|
| **M0 — Foundation** | Supabase project, full schema + RLS, magic-link auth, projects dashboard, Cloud Run skeleton, LiteLLM + Groq wired, `run_events` table | Logged-in user can create a project |
| **M1 — Hearing** | Archetype detection, seeded `assumption_classes` for all six archetypes, assumption extraction, three-axis scoring, coverage gap report, `interrupt()` + confirm UI | The assumption hearing works end to end. **This alone already changes how a founder sees their idea.** |
| **M2 — One chair deep** | Retrieval layer, tiered fetch/extract, tier assignment rules, typed claim contract, validation + repair loop, pre-persist verification, Market chair complete | First real evidence rows with live citations |
| **M3 — Boardroom** | Realtime subscription, five-column UI, remaining four chairs, `Send` fan-out, per-chair budgets, Redis caching | Five chairs investigating live on screen |
| **M4 — Conflict** | Dedup, R1–R5 as SQL, scope overlap, conflict UI, one-round cross-examination, position deltas | Founder-vs-world conflict visible and resolved |
| **M5 — Economics + Verdict** | Templates for four archetypes, `brentq` breakpoints, elasticity sensitivity, tornado chart, confidence computation, verdict gate, hung-jury path | A defensible number with a visible decomposition |
| — **CUT LINE** — | *Everything above ships regardless* | |
| **M6 — Living ledger** | Experiment generator, kill criteria, result logging, mechanical status update, affected-only re-run, versioning, diff engine, diff UI | The return-visit demo beat |
| **M7 — Polish** | Backtest on 10 companies, conflict graph, PDF export, `run_events` viewer, README, demo video, deck | Submission complete |

**Sequencing rules.** Do not build all five chairs before one works end to end — M2 exists to shake out the claim contract and the validation loop with a single corpus. Do not defer versioning to the end; retrofitting immutability onto a mutable schema is a rewrite, so insert-only evidence and snapshot-plus-diff go in at M0 even though the diff UI arrives at M6.

### 20.1 Explicit cuts

| Cut | Reason |
|---|---|
| Monte Carlo simulation | Deterministic breakpoint solve delivers the same decision value |
| Multi-round debate | One round captures nearly all the value; more rounds cost latency and token budget |
| Teams, roles, sharing beyond a token link | Not evaluated, adds surface area |
| A sixth "Visionary"-style chair | No evidence base; it was cut in design for exactly this reason |
| Code sandbox | Replaced by typed templates (§11.2 decision 4) |
| External observability platform | Replaced by `run_events` (§11.2 decision 9) |

---

## 21. Deployment runbook

### 21.1 Services

| Service | Platform | Notes |
|---|---|---|
| `jury-web` | Vercel | Next.js 15, auto-deploy from `main` |
| `jury-api` | Cloud Run | FastAPI + LangGraph, min instances 0, max 4, timeout 3600 s, 2 GB memory (embedding model resident) |
| `jury-render` | Cloud Run | Playwright-only fetch service, min instances 0, 1 GB |
| Postgres + Auth + Realtime + Storage | Supabase | Managed |
| Redis | Upstash | Managed, REST API |
| Qdrant | Qdrant Cloud | Managed, single collection |

### 21.2 Environment variables

```
# Supabase
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=        # api only
SUPABASE_JWT_SECRET=              # api only, for token validation

# LLM (single provider, overridable)
LLM_PROVIDER=groq
GROQ_API_KEY=
LLM_MODEL_REASONING=              # resolve in Groq console
LLM_MODEL_FAST=
LLM_MODEL_FALLBACK=

# Retrieval
BRAVE_API_KEY=
TAVILY_API_KEY=
EXA_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
PRODUCTHUNT_TOKEN=

# Infra
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
QDRANT_URL=
QDRANT_API_KEY=
DATABASE_URL=                     # LangGraph checkpointer
RENDER_SERVICE_URL=               # jury-render

# App
APP_BASE_URL=                     # magic-link redirect target
```

### 21.3 Deployment sequence

1. Create Supabase project; run migrations; seed `assumption_classes`; enable RLS; verify `evidence_items` denies UPDATE/DELETE.
2. Configure Auth: enable email provider, magic link only, disable signups-with-password, set redirect allowlist to `APP_BASE_URL/auth/callback`.
3. Create Upstash Redis and Qdrant collection.
4. Build `jury-render`, deploy, note URL.
5. Build `jury-api` with embedding weights baked into the image; deploy with secrets; verify `/health` and one end-to-end run via CLI.
6. Deploy `jury-web` to Vercel with public env vars; verify magic link round-trip against the deployed callback URL.
7. Pre-warm the demo project's caches.
8. Verify a cold-start run completes within the p95 target.

### 21.4 Repository structure

```
jury/
├── README.md                 # problem, architecture diagram, setup, env, run instructions
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── SCORING.md            # the formulas, published
│   └── BACKTEST.md           # eval results
├── apps/
│   ├── web/                  # Next.js
│   ├── api/                  # FastAPI + LangGraph
│   │   ├── graph/            # nodes, edges, checkpointer
│   │   ├── chairs/           # market, customer, precedent, dependencies, economics
│   │   ├── engines/          # conflict, economics, experiments, scoring, diff
│   │   ├── retrieval/        # search routing, fetch tiers, tier rules, canonicalisation
│   │   ├── llm/              # gateway config, schemas, repair loop
│   │   └── schemas/          # pydantic contracts
│   └── render/               # Playwright service
├── db/
│   ├── migrations/
│   └── seed/assumption_classes.sql
└── evals/
    ├── backtest/             # 10 companies
    └── fixtures/             # deterministic component tests
```

The README must let a judge run this. Setup instructions, env template, seed command, and one example run — that is what "clear documentation" in the submission requirements means in practice.

---

## 22. Demo script (5 minutes)

The single most important preparation decision: **choose the demo pitch deliberately.** Jury will correctly return `HUNG_JURY` on a genuinely novel idea, which is right and is terrible television. Pick something in a crowded space where real contradictions and real corpses exist, so the ledger fills and the verdict has teeth.

| Time | Beat | What's on screen |
|---|---|---|
| 0:00–0:30 | The problem, stated once | "Founders don't fail because nobody warned them. They fail because nobody checked." |
| 0:30–1:00 | Pitch submitted | Plain-language idea in a crowded category |
| 1:00–1:40 | **Assumption hearing** | Eleven assumptions extracted; three coverage gaps named — "your pitch is silent on supply liquidity and on regulatory" |
| 1:40–2:40 | **Live boardroom** | Five columns filling with cited claims; click a claim, the source opens |
| 2:40–3:20 | **Founder vs world** | R3 fires: pitch says ₹499/month, the nearest comparable charges ₹149 with visible churn in reviews. Cross-examination resolves it |
| 3:20–3:50 | **Precedent** | Three named dead companies with causes and Wayback snapshot dates. Click through to prove they existed and are gone |
| 3:50–4:20 | **Economics + verdict** | Breakpoint sentence, tornado chart, Evidence Confidence with its four components visible, verdict `PIVOT` |
| 4:20–4:50 | **The return visit** | Log a pre-sale result against its pre-registered criterion; ledger diffs live; verdict moves `PIVOT → STOP` with the causal chain rendered |
| 4:50–5:00 | Close | "Every number in this came from a URL or from arithmetic. Nothing came from an opinion." |

**Optional second beat, if time allows:** submit a genuinely novel idea and show `HUNG_JURY` — the system declining to rule and handing back three experiments. A system that says "I don't know yet, here's how to find out" is more trustworthy than one that always produces a number, and it is the clearest signal that there is a method underneath rather than a mood.

---

## 23. Hackathon deliverables mapping

| Requirement | How Jury satisfies it |
|---|---|
| **Project submission form** | Name: Jury. Description: evidence-led startup validation — five investigators build a cited record, the Jury rules on it and may refuse to rule. Links: live app, repo, video, deck. |
| **Working product** | Deployed and usable by a judge with magic-link login. No local setup required to evaluate. Every claim in the output is clickable and verifiable. |
| **Source code** | Public repo per §21.4. README with problem statement, architecture diagram, env template, migrations, seed data, and run instructions. `docs/SCORING.md` publishes the formulas, which is itself a differentiator. |
| **Demo video (≤5 min)** | Script in §22. Covers problem, mechanism, features, the specific role of AI, and a live run including the return visit. |
| **Presentation deck (≤10 slides)** | Mapping below. |

### 23.1 Deck outline (10 slides)

| # | Slide | Required topic | Content |
|---|---|---|---|
| 1 | Founders don't fail from lack of warning | Problem statement | The gap: opinion where evidence is required. Table of why existing options fail. |
| 2 | Don't build it. Prove it. | Solution overview | Five investigators → cited record → a jury that may refuse to rule. |
| 3 | Who it's for | Target users | Pre-commitment builder; the trigger moment; the return visit. |
| 4 | The assumption hearing | Product features | Assumptions extracted, three axes, coverage gaps against a hand-seeded checklist. |
| 5 | Five corpora, not five personalities | Product features | The chairs table. The point that personas converge and corpora do not. |
| 6 | Founder vs world | Product features | R3 with a real example, and cross-examination only where conflict exists. |
| 7 | Computed, not described | Product features | Breakpoint sentence, tornado chart, parameter provenance driving experiment choice. |
| 8 | The architecture | Technical architecture + AI technologies | The §10 diagram. Groq via LiteLLM, LangGraph durable orchestration, Postgres ledger with pgvector, Qdrant precedent corpus, Redis budgets. Name where AI is used and, importantly, where it is deliberately **not** — all arithmetic and all conflict detection are deterministic. |
| 9 | We tested our own judgement | Impact and value proposition | Backtest results including cause-of-death hit rate. The hung-jury rate as an honesty metric. |
| 10 | What's next | Future roadmap | §24. |

Slide 8's strongest line is the one about where AI is *not* used. In a room full of AI demos, being able to point at the parts you deliberately made deterministic is the clearest signal of engineering judgement.

---

## 24. Roadmap

| Horizon | Item | Why |
|---|---|---|
| Next | Precedent corpus compounding | Every verified precedent enriches Qdrant across all users. The only durable asset the product accumulates, and it improves with usage. |
| Next | More archetypes and deeper checklists | Coverage quality is entirely a function of hand-seeded class quality. |
| Next | Scheduled re-verification | Sources decay. Re-fetch tier-1 sources monthly and flag claims whose evidence has changed — competitor raised prices, competitor died. |
| Mid | Investor-facing read-only ledger | Turns the case file into a diligence artifact. A natural distribution channel: founders share it, investors discover the product. |
| Mid | Accelerator / cohort mode | Batch validation with aggregate coverage reporting. The clearest B2B wedge. |
| Mid | Experiment integrations | Pull results automatically from a landing-page analytics provider or a payments provider instead of manual logging. |
| Later | Region-specific regulatory packs | Dependencies chair becomes materially stronger with curated regulator source maps per jurisdiction. |
| Later | Calibration loop | Track real outcomes of validated projects and calibrate the confidence weights against them. The honest long-term version of the backtest. |

---

## 25. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Open-weight structured-output unreliability | **High** | Mandatory validation + repair + field-split fallback (§15.3). Budget real time for this; it is the largest reliability risk in the build. |
| Single LLM provider is a single point of failure | **High** | Model-level fallback chain, prompt-hash response caching, pre-warmed demo cache, documented provider override env var. |
| Precedent retrieval returns thin or fabricated results | **High** | Pre-persist fetch verification (no 2xx, no row); Wayback verification; widen to outcomes; accept "no precedent found" as a valid finding. |
| Coverage score becomes self-graded | **High** | `assumption_classes` is hand-seeded static data. Never generate it at runtime. This is the one shortcut that would hollow out the whole product. |
| Search quota exhausted during judging | Medium | Per-chair budgets, aggressive caching, provider fallback, pre-warmed demo. |
| Run latency makes the demo drag | Medium | Parallel fan-out, per-chair budgets, pre-warmed cache, and a recorded fallback run available. |
| Scope creep into six chairs and multi-round debate | Medium | The cut line in §20 is binding. |
| Playwright bloats the image and slows cold starts | Medium | Separate `jury-render` service. |
| SSRF via model-selected URLs | Medium | Allowlist/blocklist, private-range blocking, no metadata endpoints. |
| Judges read "startup validator" as a saturated category | Medium | Lead with the clickable citation and the hung jury, not with the boardroom. The demo must prove checkability in the first ninety seconds. |
| Free-tier limits change without notice | Low | Verify every limit at signup; keep the provider abstraction thin enough to swap. |

---

## 26. Open questions

1. **Archetype breadth vs depth.** Six archetypes seeded shallowly, or three seeded deeply? Depth improves coverage quality where it is measured; breadth avoids a demo failing on an unsupported model. Recommendation: seed three deeply (marketplace, subscription SaaS, D2C) and three at minimum viable depth, and detect-with-override so nothing hard-fails.
2. **Target scope capture.** Should `projects.target_scope` be asked explicitly at intake, or inferred from the pitch and confirmed? Explicit is more reliable and makes R5 scope gaps meaningful, at the cost of one more intake field. Recommendation: explicit, with an inferred default.
3. **Confidence weights.** The 0.30/0.30/0.20/0.20 split in §9.3 is a considered judgement, not a calibrated result. The backtest may indicate a different split. Publish whatever is used, and publish that it was chosen rather than fitted.
4. **Tier-4 evidence weight.** Forum anecdote at 0.30 may be too generous for willingness-to-pay claims specifically, where stated intent is notoriously unreliable. Consider a per-variable tier adjustment.
5. **Return-visit re-run scope.** Recompute only assumptions directly downstream of the changed parameter, or re-run the full graph? Affected-only is faster and makes the diff cleaner; full re-run catches second-order effects. Recommendation: affected-only, with a manual full re-run available.
6. **Retention testability.** No 30-day experiment can measure retention honestly. The current answer is a flagged proxy. This is a genuine methodological limitation and should be stated in the product rather than papered over.

---

*End of document.*