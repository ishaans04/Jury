"""The shared chair pipeline. Task 3.7. PRD §6, §16.1, §18.

Every investigator chair (Market first, in this batch; Customer, Precedent,
Dependencies and Economics follow the same shape in later phases) is a query
strategy plus a claim-extraction prompt, nothing more -- budget spending,
search, fetch, extraction, verification, persistence and tracing all live
here exactly once, in `run_chair`.

**Ordering is a hard guarantee, not an implementation detail.** `verify_claim`
(the P1 integrity gate, jury/retrieval/verify.py) always runs BEFORE any row
is written, and `SourceRepo.upsert`/`EvidenceRepo.insert_verified` are only
ever called from inside the branch where `verify_claim` returned a
`VerifiedClaim` -- never from the `Rejection` branch. A rejected claim's loop
iteration simply appends to `result.rejected` and moves on; no source row,
orphan or otherwise, is ever created for it. This is enforced by control
flow, not by an after-the-fact cleanup: the code path that could write a
source row for a rejected claim does not exist, the same way `EvidenceRepo`
(jury/db/repositories.py) has no update method at all rather than an unused
one.

Decisions made in this module that the brief left open (see the batch report
for the full reasoning):
  - one search provider per chair (its first entry in
    `budgets.CHAIR_PROVIDERS`), not a fan-out across all of a chair's routed
    providers -- multi-provider fan-out per query is a future enhancement.
  - one claim-extraction call per fetched page (via `structured_report`
    against `ClaimRecord` directly), not `structured_many` -- a page is
    treated as evidence for at most one claim per visit.
  - a budget token is spent on every *attempted* query, before the search
    call, regardless of whether that search returns hits, an empty list, or
    degrades silently (missing credential, flaky provider). See the batch
    report for why counting attempts rather than successes is the only
    version of "35 queries total" that is actually a hard cap.
  - a claim whose `assumption_id` names an assumption not in `ctx.assumptions`
    is treated as a rejection (defensive: nothing in `ClaimRecord` itself
    constrains `assumption_id` to the run's own assumptions, and the FK would
    otherwise raise inside `EvidenceRepo.insert_verified`).
  - a chair-discovered assumption (`claim.new_assumption`) is persisted via
    `AssumptionRepo.create_discovered` with fixed default
    criticality/uncertainty/falsifiability, since a chair has no principled
    basis yet for guessing those from a single page -- Phase 4's founder-facing
    review is where they get refined.
  - `persist_chunks` runs after the evidence insert, on the same await chain,
    never inside a held database transaction of its own: embedding is CPU/
    model-bound work that can be slow for a large page, and none of the
    repository calls above hold a transaction open across it (`SourceRepo`/
    `EvidenceRepo` each open and close their own short transaction per call),
    so a slow embedding pass blocks nothing but this one claim's own loop
    iteration, never a database connection.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from jury.db.repositories import AssumptionRepo, EvidenceRepo, SourceRepo
from jury.llm.structured import structured_report
from jury.retrieval.embed import Embedder, persist_chunks
from jury.retrieval.budgets import BudgetLedger
from jury.retrieval.extract import chunk
from jury.retrieval.verify import Rejection, verify_claim
from jury.schemas.assumption import AssumptionRecord
from jury.schemas.claim import ClaimRecord, NewAssumption
from jury.schemas.enums import Chair
from jury.schemas.scope import Scope
from jury.tracing.events import TraceSink
from jury.transport.protocols import SearchHit, Transports

DEFAULT_SEARCH_LIMIT = 3

# A chair-discovered assumption (PRD §7.3) arrives with only a statement and a
# class_key -- ClaimRecord.new_assumption (jury/schemas/claim.py) carries
# nothing else. These are deliberately middling defaults: a chair has just
# found one piece of evidence for something the extractor missed, which is
# neither "no signal yet" (unknown/untestable) nor "well established"; Phase
# 4's founder-facing review is where these get refined, not this pipeline.
_DISCOVERED_CRITICALITY = "medium"
_DISCOVERED_UNCERTAINTY = "uncertain"
_DISCOVERED_FALSIFIABILITY = "testable_costly"


@dataclass(slots=True)
class ChairContext:
    run_id: str
    project_id: str
    pitch: str
    target_scope: Scope
    assumptions: list[AssumptionRecord]
    transports: Transports
    budgets: BudgetLedger
    domain_map: dict[str, int]
    trace: TraceSink | None
    pool: object
    embedder: Embedder


@dataclass(slots=True)
class ChairResult:
    inserted: list[str] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    discovered: list[NewAssumption] = field(default_factory=list)
    partial: bool = False
    no_precedent_found: bool = False


QueryBuilder = Callable[[ChairContext], list[str]]
PromptBuilder = Callable[[ChairContext, SearchHit, str], str]
ClaimGuard = Callable[[ClaimRecord], str | None]


def _domain_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


async def _emit_fetch_trace(ctx: ChairContext, chair: Chair, url: str, status: int,
                            started: float) -> None:
    if ctx.trace is None:
        return
    await ctx.trace.emit(
        node=chair.value, event="fetch", detail={"url": url, "status": status},
        latency_ms=int((time.perf_counter() - started) * 1000))


async def run_chair(ctx: ChairContext, *, chair: Chair, provider: str, llm_role: str,
                    build_queries: QueryBuilder, build_prompt: PromptBuilder,
                    search_limit: int = DEFAULT_SEARCH_LIMIT,
                    claim_guard: ClaimGuard | None = None) -> ChairResult:
    """The pipeline every chair shares. See the module docstring for the
    ordering guarantee and the decisions this function makes on the brief's
    behalf.

    `claim_guard` (Task 4.2, added for Dependencies) is an optional
    chair-specific check that runs on the raw extracted `ClaimRecord`,
    strictly BEFORE `verify_claim` -- i.e. before any network fetch of the
    claim's source is attempted for verification purposes, and long before
    any source/evidence row could be written. It returns a rejection reason
    string to reject the claim (appended to `result.rejected` exactly like a
    `verify_claim` rejection, so callers cannot tell the two apart by shape)
    or `None` to let the claim proceed through the normal integrity gate.
    Every other chair passes `None` and this parameter changes nothing about
    their behaviour."""
    result = ChairResult()
    known_assumption_ids = {a.id for a in ctx.assumptions}
    source_repo = SourceRepo(ctx.pool)
    evidence_repo = EvidenceRepo(ctx.pool)
    assumption_repo = AssumptionRepo(ctx.pool)

    for query in build_queries(ctx):
        # Budget is spent on the attempt, not the outcome (see module
        # docstring): a provider degrading to [] must not look different to
        # the ledger than a provider that returned real hits.
        if not await ctx.budgets.spend(chair, provider):
            result.partial = True
            break

        hits = await ctx.transports.search.search(provider=provider, query=query,
                                                   limit=search_limit)
        for hit in hits:
            if not hit.url:
                continue

            started = time.perf_counter()
            fetched = await ctx.transports.fetch.fetch(hit.url)
            await _emit_fetch_trace(ctx, chair, hit.url, fetched.status, started)
            if not (200 <= fetched.status < 300) or not fetched.text.strip():
                continue

            pieces = chunk(fetched.text)
            page_text = pieces[0] if pieces else fetched.text
            prompt = build_prompt(ctx, hit, page_text)
            report = await structured_report(
                ctx.transports.llm, role=llm_role, prompt=prompt,
                schema=ClaimRecord, trace=ctx.trace)
            claim = report.value
            if claim is None:
                # PRD §15.3 mitigation 5: a claim that fails every repair
                # stage vanishes silently rather than becoming a gap the
                # caller must special-case.
                continue

            if claim_guard is not None:
                guard_reason = claim_guard(claim)
                if guard_reason is not None:
                    result.rejected.append(Rejection(claim, guard_reason))
                    continue

            verified_or_rejection = await verify_claim(
                claim, ctx.transports.fetch, domain_map=ctx.domain_map)
            if isinstance(verified_or_rejection, Rejection):
                # THE integrity guarantee: nothing below this line ever runs
                # for a rejected claim. No SourceRepo call, no
                # EvidenceRepo call -- so no source row, orphaned or
                # otherwise, and no evidence row, can ever exist for it.
                result.rejected.append(verified_or_rejection)
                continue
            verified = verified_or_rejection

            assumption_id = claim.assumption_id
            if claim.new_assumption is not None:
                assumption_id = await assumption_repo.create_discovered(
                    ctx.project_id, ctx.run_id, chair.value,
                    claim.new_assumption.class_key, claim.new_assumption.statement,
                    _DISCOVERED_CRITICALITY, _DISCOVERED_UNCERTAINTY,
                    _DISCOVERED_FALSIFIABILITY)
                result.discovered.append(claim.new_assumption)
            elif assumption_id not in known_assumption_ids:
                result.rejected.append(Rejection(
                    claim, "assumption_id not recognised for this run"))
                continue

            source_id = await source_repo.upsert(
                canonical_url=verified.canonical_url,
                domain=_domain_of(verified.canonical_url), tier=verified.tier,
                title=hit.title or None, http_status=verified.http_status)

            evidence_id = await evidence_repo.insert_verified(
                project_id=ctx.project_id, run_id=ctx.run_id,
                assumption_id=assumption_id, source_id=source_id, verified=verified)
            # P10: a duplicate dedup_hash returns None. That is a correct,
            # expected no-op -- not a newly-inserted row, and not a rejection
            # either (the claim was perfectly valid; it just already exists).
            if evidence_id is not None:
                result.inserted.append(evidence_id)

            # Chunks hang off the source, not the claim: this runs once per
            # source regardless of how many claims end up citing it, and
            # persist_chunks (jury/retrieval/embed.py) is idempotent on
            # source_id so a second claim citing the same source is a cheap
            # no-op here.
            await persist_chunks(ctx.pool, source_id, verified.extracted_text,
                                 ctx.embedder)

    return result
