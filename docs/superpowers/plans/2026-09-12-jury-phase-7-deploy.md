# Phase 7 — Deploy, Document, Backtest

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **PRD:** §19 (evaluation and backtest), §21 (deployment runbook), §22 (demo script), §23 (deliverables mapping)

**Phase goal:** A judge with a browser and no local setup can log in, run Jury, click through to a real source, and read the published scoring formulas and the backtest of Jury's own judgement.

**Why the backtest is worth the time (PRD §19, verbatim):** *"Almost nobody at a hackathon ships an evaluation of their own product's judgement. This is the cheapest credibility available and it belongs in the deck."*

**Gate:** a cold-start run on the deployed stack completes within PRD §17.1's p95 (9 min), and a clean machine can follow `README.md` to a working local install.

---

## File structure

| Path | Responsibility |
|---|---|
| `apps/api/Dockerfile` | `jury-api` image with embedding weights baked in |
| `apps/api/.dockerignore` | |
| `apps/web/vercel.json` | |
| `README.md` | Problem, architecture, setup, env, run instructions |
| `docs/ARCHITECTURE.md` | The §10 diagram plus the decisions that matter |
| `docs/SCORING.md` | Written in Phase 1; completed here |
| `docs/BACKTEST.md` | Eval results |
| `docs/DEMO.md` | The §22 script with real timings |
| `evals/backtest/companies.json` | 3 companies with known outcomes |
| `evals/backtest/run_backtest.py` | Harness |
| `evals/fixtures/` | Deterministic component fixtures (already populated) |
| `scripts/prewarm_demo.py` | Records fixtures for the demo pitch |

---

### Task 7.1: Container image

**Files:** Create `apps/api/Dockerfile`, `.dockerignore`; Test `tests/test_container.py`

**PRD §15.3 requirement:** *"bake weights into the image at build time; warm on container start; cache embeddings in Redis keyed by content hash."* Cold start target is **≤8s** (PRD §17.1), and `jury-api` runs with 2 GB memory because the embedding model is resident (PRD §21.1).

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/opt/fastembed

RUN apt-get update && apt-get install -y --no-install-recommends \
      libxml2 libxslt1.1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# PRD §15.3: bake the embedding weights so a cold start does not download them.
RUN uv run python -c "\
from fastembed import TextEmbedding; \
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed'); \
print('embedding weights baked')"

COPY jury ./jury
RUN uv sync --frozen --no-dev

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "jury.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Write the failing test**

```python
# apps/api/tests/test_container.py
import pathlib
import re

DOCKERFILE = (pathlib.Path(__file__).parents[1] / "Dockerfile").read_text()


def test_the_image_pins_python_312():
    """3.14 has no onnxruntime wheels and fastembed is load-bearing (PRD §15.3)."""
    assert "python:3.12" in DOCKERFILE


def test_embedding_weights_are_baked_at_build_time():
    """PRD §15.3 mitigation: the container must not download weights on cold start."""
    assert "fastembed" in DOCKERFILE.lower()
    assert "FASTEMBED_CACHE_PATH" in DOCKERFILE


def test_dependencies_are_installed_before_source_is_copied():
    """Otherwise every source edit reinstalls the whole dependency tree."""
    deps = DOCKERFILE.index("uv sync")
    src = DOCKERFILE.index("COPY jury")
    assert deps < src


def test_dev_dependencies_are_excluded_from_the_image():
    assert "--no-dev" in DOCKERFILE


def test_the_container_listens_on_the_cloud_run_port():
    assert "8080" in DOCKERFILE


def test_no_secret_is_baked_into_the_image():
    """PRD §17.4: secrets in Cloud Run secret env vars. Nothing in the repo."""
    for pattern in (r"GROQ_API_KEY\s*=\s*\S", r"SERVICE_ROLE_KEY\s*=\s*\S",
                    r"sk-[A-Za-z0-9]{10,}"):
        assert not re.search(pattern, DOCKERFILE), pattern


def test_the_dockerignore_excludes_env_and_tests():
    ignore = (pathlib.Path(__file__).parents[1] / ".dockerignore").read_text()
    for entry in (".env", "tests", ".venv"):
        assert entry in ignore
```

- [ ] **Step 3: Build and measure cold start**

```bash
cd apps/api && docker build -t jury-api:local .
docker run --rm -p 8080:8080 -e JURY_OFFLINE=1 jury-api:local &
time curl -sf http://localhost:8080/health
```
Expected: `{"status":"ok"}` within **8s** of container start. Record the measured figure.

- [ ] **Step 4: Verify the tests pass**
- [ ] **Step 5: Commit** — `git commit -m "chore(api): container image with baked embedding weights"`

---

### Task 7.2: Deploy

Follows PRD §21.3's sequence, minus the cut steps (no `jury-render`, no Qdrant).

- [ ] **Step 1: Supabase** — create the project, run migrations, seed `assumption_classes` and `domain_tiers`, enable RLS, and **verify `evidence_items` denies UPDATE/DELETE on the hosted instance** (Phase 0's constraint test against the hosted DSN, not just local).
- [ ] **Step 2: Auth** — enable email, magic link only, **disable signups-with-password**, set the redirect allowlist to `APP_BASE_URL/auth/callback`.
- [ ] **Step 3: Upstash Redis** — create, note the REST URL and token.
- [ ] **Step 4: Cloud Run** — deploy `jury-api`:
```bash
gcloud run deploy jury-api \
  --source apps/api --region asia-south1 \
  --memory 2Gi --cpu 2 --timeout 3600 \
  --min-instances 0 --max-instances 4 \
  --set-env-vars LLM_PROVIDER=groq,JURY_OFFLINE=0 \
  --set-secrets GROQ_API_KEY=groq-key:latest,SUPABASE_SERVICE_ROLE_KEY=sb-service:latest,SUPABASE_JWT_SECRET=sb-jwt:latest,DATABASE_URL=db-url:latest,BRAVE_API_KEY=brave:latest,UPSTASH_REDIS_REST_URL=upstash-url:latest,UPSTASH_REDIS_REST_TOKEN=upstash-token:latest \
  --allow-unauthenticated
```
- [ ] **Step 5: Verify `/health` and one end-to-end run via CLI** before touching the frontend.
- [ ] **Step 6: Vercel** — deploy `apps/web` with the public env vars; verify the magic-link round trip against the **deployed** callback URL.
- [ ] **Step 7: Pre-warm the demo caches** — `uv run python scripts/prewarm_demo.py` with `RecordingLLMClient` so the demo pitch's LLM, search and fetch responses are all cached. This is PRD §21.3 step 7 and it is also the §25 mitigation for Groq degrading mid-judging.
- [ ] **Step 8: Verify a cold-start run completes within the p95 target** and record the measured wall clock.

- [ ] **Step 9: Post-deploy smoke test**

```python
# apps/api/tests/test_deployed_smoke.py  (marked @pytest.mark.deployed, opt-in)
@pytest.mark.deployed
async def test_health_responds_on_the_deployed_api():
    assert (await httpx.AsyncClient().get(f"{BASE}/health")).status_code == 200


@pytest.mark.deployed
async def test_an_unauthenticated_request_is_rejected_in_production():
    assert (await httpx.AsyncClient().get(f"{BASE}/projects")).status_code == 401


@pytest.mark.deployed
async def test_evidence_is_immutable_on_the_hosted_database():
    """The single most important thing to re-verify after deploy: a local-only
    immutability guarantee is worth nothing."""
    with pytest.raises(Exception):
        await hosted_update_evidence_row()
```

- [ ] **Step 10: Commit** — `git commit -m "chore: deployment configuration for cloud run and vercel"`

---

### Task 7.3: Backtest harness

**Files:** Create `evals/backtest/companies.json`, `run_backtest.py`, `docs/BACKTEST.md`; Test `tests/evals/test_backtest_harness.py`

**PRD §19.1 method:** for each company, reconstruct a pitch using **only information available at their seed stage**, and restrict retrieval to sources predating that date where feasible.

**Reported metrics (PRD §19.1):**

| Metric | Definition |
|---|---|
| Directional accuracy | `PROCEED`/`PIVOT` aligned with survival, `STOP` aligned with shutdown |
| Hung-jury rate | Fraction where the system correctly declined to rule |
| Cause-of-death hit rate | For dead companies, whether the actual cause appeared as a `refuted` or `contested` assumption |

PRD calls cause-of-death hit rate *"the most honest and most impressive of the three: it tests whether Jury found the right reason, not just the right label."*

**Spec §4:** 10 companies → **3** (2 dead, 1 survived), reported honestly as `n=3`. The harness takes N, so extending it later is data entry.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/evals/test_backtest_harness.py
def test_the_company_set_declares_outcomes_and_causes():
    companies = json.loads(COMPANIES.read_text())
    assert len(companies) >= 3
    for c in companies:
        assert c["outcome"] in {"survived", "shutdown", "pivoted"}
        assert c["seed_stage_date"]
        assert 200 <= len(c["reconstructed_pitch"]) <= 2000
        if c["outcome"] == "shutdown":
            assert c["actual_cause"] and c["cause_source_url"]


def test_every_cause_claim_carries_a_source():
    """The backtest must not assert a cause of death without a citation —
    the product's own standard applies to its evaluation."""
    for c in json.loads(COMPANIES.read_text()):
        if c.get("actual_cause"):
            assert c["cause_source_url"].startswith("http")


def test_directional_accuracy_scoring_is_correct():
    assert score_direction("PROCEED", "survived") is True
    assert score_direction("PIVOT", "survived") is True
    assert score_direction("STOP", "shutdown") is True
    assert score_direction("PROCEED", "shutdown") is False
    assert score_direction("STOP", "survived") is False


def test_a_hung_jury_is_excluded_from_directional_accuracy():
    """A refusal is neither right nor wrong about direction; counting it either
    way would let the system game the metric by always hanging."""
    assert score_direction("HUNG_JURY", "survived") is None
    assert score_direction("HUNG_JURY", "shutdown") is None


def test_hung_jury_rate_is_reported_separately():
    report = summarise([{"verdict": "HUNG_JURY"}, {"verdict": "STOP"}])
    assert report["hung_jury_rate"] == 0.5


def test_cause_of_death_hit_requires_a_refuted_or_contested_assumption():
    assumptions = [{"statement": "Suppliers will accept a 20% commission.",
                    "status": "refuted"}]
    assert score_cause("supply side refused the commission", assumptions) is True
    assert score_cause("ran out of runway", assumptions) is False


def test_cause_of_death_ignores_supported_assumptions():
    """Finding the right topic while concluding the opposite is not a hit."""
    assumptions = [{"statement": "Suppliers will accept a 20% commission.",
                    "status": "supported"}]
    assert score_cause("supply side refused the commission", assumptions) is False


def test_the_report_states_the_sample_size_explicitly():
    """Spec §4: report n=3 honestly rather than implying ten."""
    report = summarise([{"verdict": "STOP"}] * 3)
    assert report["n"] == 3


def test_the_harness_runs_offline_against_fixtures():
    """Otherwise the backtest burns the search quota that judging needs."""
    report = run_backtest(offline=True)
    assert report["n"] >= 3
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Choose the three companies and write `companies.json`.** Selection criteria: a documented public postmortem with a citable URL, a reconstructable seed-stage pitch, and an archetype Jury has a template for. Each shutdown entry needs `actual_cause` plus `cause_source_url`.
- [ ] **Step 4: Implement `run_backtest.py`.** For each company: create a project, run the full graph offline against recorded pre-date fixtures, capture the verdict and assumption statuses, score all three metrics. Emit `docs/BACKTEST.md`.
- [ ] **Step 5: Run it and write the real numbers**
```bash
cd apps/api && uv run python ../../evals/backtest/run_backtest.py --offline --out ../../docs/BACKTEST.md
```
`docs/BACKTEST.md` must state `n=3`, the three metrics, **and the limitations** — reconstructed pitches carry hindsight bias, and retrieval cannot be fully restricted to pre-date sources. Publishing the limitation is the credibility, not the number.
- [ ] **Step 6: Commit** — `git commit -m "feat(evals): three-company verdict backtest with published limitations"`

---

### Task 7.4: Component eval report

**Files:** Create `evals/run_component_evals.py`; append results to `docs/BACKTEST.md`

**PRD §19.2 table — deterministic components must score 100%:**

| Component | Test | Pass bar |
|---|---|---|
| Assumption extraction | 20 pitches, human-labelled | ≥80% recall on blocking assumptions |
| Source tier assignment | 100 labelled URLs | ≥95% |
| Conflict engine | Synthetic fixtures | **100%** |
| Scope overlap | Fixture matrix | **100%** |
| Hallucination guard | 50 fabricated names | **100%** |
| Economics solver | Hand-computed fixtures | **Exact** |
| Kill-criterion evaluation | Fixture results | **100%** |

Six of the seven already have their tests from Phases 1 and 3. This task adds the extraction eval (20 labelled pitches) and the report that prints all seven with actual numbers.

- [ ] **Step 1: Build `evals/fixtures/pitches_labelled.json`** — 20 pitches, each with human-labelled blocking assumptions.
- [ ] **Step 2: Write the eval test**

```python
async def test_extraction_recall_on_blocking_assumptions_meets_the_bar():
    """PRD §19.2: >=80% recall on blocking assumptions across 20 pitches."""
    recall = await measure_extraction_recall(PITCHES, offline=True)
    assert recall >= 0.80, f"recall {recall:.2%} below the 80% bar"


def test_the_report_prints_every_row_of_the_prd_table():
    report = run_component_evals()
    assert set(report) == {"assumption_extraction", "source_tier", "conflict_engine",
                           "scope_overlap", "hallucination_guard",
                           "economics_solver", "kill_criterion"}


def test_every_deterministic_component_scores_exactly_100_percent():
    """PRD §19.2: 'Deterministic components must score 100%. That is the point
    of making them deterministic.'"""
    report = run_component_evals()
    for key in ("conflict_engine", "scope_overlap", "hallucination_guard",
                "economics_solver", "kill_criterion"):
        assert report[key]["score"] == 1.0, f"{key} scored {report[key]['score']}"
```

- [ ] **Step 3: Implement and run**
```bash
cd apps/api && uv run python ../../evals/run_component_evals.py --append ../../docs/BACKTEST.md
```
- [ ] **Step 4: Commit** — `git commit -m "feat(evals): component eval report against the PRD §19.2 bars"`

---

### Task 7.5: README and documentation

**Files:** `README.md`, `docs/ARCHITECTURE.md`, `docs/SCORING.md` (complete it), `docs/DEMO.md`

**PRD §21.4's standard, verbatim:** *"The README must let a judge run this. Setup instructions, env template, seed command, and one example run — that is what 'clear documentation' in the submission requirements means in practice."*

- [ ] **Step 1: Write `README.md`**

Required sections:
1. **Don't build it. Prove it.** — the one-line problem statement and the differentiator: *every number is traceable to a fetchable URL or an executed arithmetic model.*
2. Live app link, repo, video, deck (PRD §23).
3. The architecture diagram from PRD §10.
4. **Where AI is used, and where it is deliberately not** — all arithmetic and all conflict detection are deterministic. PRD §23.1: *"Slide 8's strongest line is the one about where AI is not used."*
5. Quickstart: `git clone` → `cp .env.example .env` → `npx supabase start` → `uv sync` → `npm install` → `npx supabase db reset` (applies migrations + seeds) → `uv run uvicorn` → `npm run dev`.
6. **Running with no credentials:** `JURY_OFFLINE=1` runs the full pipeline from fixtures. State this prominently — it is how a judge evaluates without provisioning seven API keys.
7. Credential unblocking order: Supabase → Groq → Brave → Exa → Reddit → Tavily → Upstash, and which chair each one activates.
8. Test commands: `uv run pytest -q`, `npm test`, `uv run python evals/run_component_evals.py`.
9. Links to `docs/SCORING.md` and `docs/BACKTEST.md`.

- [ ] **Step 2: Write the test that keeps the README honest**

```python
# apps/api/tests/test_docs.py
README = (pathlib.Path(__file__).parents[3] / "README.md").read_text()


def test_the_readme_documents_the_offline_mode():
    assert "JURY_OFFLINE" in README


def test_the_readme_documents_every_env_var_from_the_example():
    names = [l.split("=")[0] for l in ENV_EXAMPLE.splitlines()
             if "=" in l and not l.startswith("#")]
    missing = [n for n in names if n not in README]
    assert not missing, f"undocumented env vars: {missing}"


def test_the_readme_contains_a_runnable_quickstart():
    for cmd in ("supabase start", "uv sync", "npm install", "db reset"):
        assert cmd in README


def test_the_readme_states_where_ai_is_not_used():
    lowered = README.lower()
    assert "deterministic" in lowered


def test_scoring_doc_publishes_the_confidence_weights():
    scoring = SCORING.read_text()
    for weight in ("0.30", "0.20"):
        assert weight in scoring


def test_scoring_doc_states_the_weights_were_chosen_not_fitted():
    """Spec §26.3: publish whatever is used, and publish that it was chosen
    rather than fitted."""
    assert "chosen" in SCORING.read_text().lower()


def test_scoring_doc_publishes_every_conflict_rule():
    scoring = SCORING.read_text()
    for rule in ("R1", "R2", "R3", "R4", "R5"):
        assert rule in scoring


def test_scoring_doc_publishes_the_exact_conflict_thresholds():
    scoring = SCORING.read_text()
    assert "10%" in scoring and "25%" in scoring


def test_architecture_doc_records_the_cut_decisions():
    """A reader should be able to tell what was cut and why, not guess."""
    arch = ARCHITECTURE.read_text()
    for cut in ("Qdrant", "Playwright"):
        assert cut in arch
```

- [ ] **Step 3: Write `docs/ARCHITECTURE.md`** — the §10 diagram, the §11.2 decisions that matter, and the spec §4 cuts with their reasons.
- [ ] **Step 4: Write `docs/DEMO.md`** — the §22 script with the **measured** timings from the deployed stack, plus a note that the pre-warmed cache means the demo survives a Groq outage.
- [ ] **Step 5: Verify the doc tests pass**
- [ ] **Step 6: Commit** — `git commit -m "docs: README, architecture, scoring and demo script"`

---

### Task 7.6: Final gate

- [ ] **Step 1: Full suite, offline**
```bash
cd apps/api && JURY_OFFLINE=1 uv run pytest -q
npm run test --workspace apps/web
npx playwright test --workspace apps/web
```

- [ ] **Step 2: Clean-machine check.** In a fresh clone, follow the README exactly and confirm it reaches a working local install with **no** steps missing. A README that only works on the author's machine fails PRD §23.

- [ ] **Step 3: Deployed cold-start timing**
```bash
cd apps/api && uv run python scripts/timed_run.py --base "$DEPLOYED_API" --pitch demo
```
Record hearing-ready, first-row, and total wall clock against PRD §17.1's targets (45s / 20s / 5 min p50, 9 min p95).

- [ ] **Step 4: Verify §23's deliverables mapping**

| Requirement | Check |
|---|---|
| Working product | Judge logs in with a magic link, runs it, clicks a citation through to the live source |
| Source code | Public repo; README with problem, diagram, env template, migrations, seeds, run instructions |
| `docs/SCORING.md` | Formulas published, weights declared as chosen not fitted |
| Demo video ≤5 min | §22 script; covers problem, mechanism, features, the specific role of AI, live run + return visit |
| Deck ≤10 slides | §23.1 mapping |

- [ ] **Step 5: Final `CHANGELOG.md` entry** — every measured number in one place: test counts, hallucination guard 50/50, tier accuracy, extraction recall, the three backtest metrics with `n=3`, cold start, first row, total run time, and the complete list of deviations from PRD.md accumulated across all seven phases.

- [ ] **Step 6: Push**
```bash
git add -A
git commit -m "docs: final changelog with measured results across all phases"
git push origin main
```

---

## Phase 7 exit criteria

- [ ] Image pins Python 3.12, bakes embedding weights, excludes dev deps and secrets
- [ ] Cold start `/health` within **8s** (record the figure)
- [ ] Hosted Supabase migrations applied, RLS on, and **evidence immutability re-verified against the hosted DB**
- [ ] Auth is magic-link only with password signups disabled and the redirect allowlist set
- [ ] `jury-api` on Cloud Run: 2 GB, 3600s timeout, min 0 / max 4
- [ ] One end-to-end run verified via CLI **before** the frontend is wired
- [ ] Magic-link round trip verified against the **deployed** callback URL
- [ ] Demo caches pre-warmed; documented as the Groq-outage fallback
- [ ] Backtest run on 3 companies; all three PRD §19.1 metrics reported with `n=3` stated
- [ ] Every backtest cause-of-death claim carries a source URL
- [ ] `HUNG_JURY` excluded from directional accuracy and reported as its own rate
- [ ] All five deterministic components score **exactly 100%**
- [ ] Extraction recall ≥80%; tier accuracy ≥95% (record both)
- [ ] `docs/SCORING.md` publishes weights, the "chosen not fitted" statement, R1–R5 and their exact thresholds
- [ ] `docs/ARCHITECTURE.md` records the Qdrant and Playwright cuts with reasons
- [ ] README documents every env var in `.env.example`, the offline mode, and a runnable quickstart
- [ ] A clean clone reaches a working install by following the README alone
- [ ] Deployed cold-start run within the p95 target (record the figure)
- [ ] `CHANGELOG.md` lists every measured number and every deviation from PRD.md
