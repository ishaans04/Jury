"""The Dependencies chair. Task 4.2. PRD §6.2.

What the idea requires from the outside world: a payment processor's
published fee, a regulator's licence requirement, an API's documented rate
ceiling, a supplier's listed lead time. PRD §6.2 names this chair's real
risk explicitly: it "has the thinnest natural corpus and will drift into
opinion if unconstrained" -- "this will be hard to build" is the old
persona wearing a new badge. `_dependency_guard` below is the hard rule
that keeps it out.

**How the guard actually decides (Task 4.2 asks this to be stated
plainly):** it is a purely STRUCTURAL check on the extracted `ClaimRecord`
-- `variable` must be set AND at least one of `value_num` / `value_min` /
`unit` must be set -- run as `base.run_chair`'s `claim_guard` hook, before
`verify_claim`. It is deliberately NOT a lexical/keyword check on the
`excerpt` text (e.g. "does the excerpt contain a capitalised word / a
vendor name"). Two reasons, not one:

  1. It would reject the brief's own canonical accepted example. PRD §6.2's
     worked "published per-call price" case is exactly
     `("stripe_api_price", "Standard pricing is 2.9% plus 30 cents per
     charge.")` -- an excerpt that names no vendor at all in its own text;
     the dependency is named by the claim's structured `variable` field
     ("stripe_api_price"), not by a proper noun inside the excerpt. A
     literal "the excerpt must name an entity" regex would reject this
     true positive.
  2. It is the wrong direction of gameability. A lexical entity-in-excerpt
     check can be satisfied by an opinion that happens to mention a vendor
     name ("Stripe will be hard to integrate.") while carrying no citable
     property at all -- exactly the failure mode this guard exists to
     close. The structural check cannot be satisfied that way: an opinion
     sentence has nowhere to put a `variable` name or a `value_num`/`unit`
     without the extractor inventing a fake one, and a fabricated numeric
     value is a `verify_claim` problem (excerpt-verbatim, source-fetched)
     the pipeline already polices independently, downstream of this guard.

So "a specific external dependency with a citable property" is enforced as
"a variable name plus a value or unit" -- a property, not a sentence -- and
nothing more. See the batch report for the full reasoning and the tension
this creates with PRD §6.2's own phrasing ("names a domain-bearing
entity"), which is not fully separable from the structural check without
rejecting the brief's own accepted example.
"""
from jury.chairs.base import ChairContext, ChairResult, run_chair
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS
from jury.schemas.claim import ClaimRecord
from jury.schemas.enums import Chair
from jury.transport.protocols import SearchHit

_PROVIDER = CHAIR_PROVIDERS[Chair.DEPENDENCIES][0]     # "brave" -- only entry.
_LLM_ROLE = "dependencies_extract"

_BASE_QUERY_SUFFIXES = (
    "API pricing per call", "API rate limit documentation",
    "licence requirement regulator", "compliance requirement",
    "supplier lead time",
)


def _dependency_guard(claim: ClaimRecord) -> str | None:
    """PRD §6.2's hard rule, enforced structurally. See module docstring."""
    if not claim.variable:
        return "no specific external dependency named (variable is null)"
    if claim.value_num is None and claim.value_min is None and claim.unit is None:
        return ("no citable property on the named dependency "
                "(no value_num/value_min/unit) -- an opinion, not a property")
    return None


def _build_queries(ctx: ChairContext) -> list[str]:
    pitch = ctx.pitch.strip()
    queries = [f"{pitch} {suffix}" for suffix in _BASE_QUERY_SUFFIXES]
    unique = list(dict.fromkeys(queries))
    return unique[:CHAIR_BUDGETS[Chair.DEPENDENCIES]]


def _build_prompt(ctx: ChairContext, hit: SearchHit, page_text: str) -> str:
    return (
        "You are the Dependencies investigator for a startup evaluation "
        "system.\n"
        f"Founder's pitch: {ctx.pitch}\n"
        f"Target scope: geo={ctx.target_scope.geo.value}, "
        f"segment={ctx.target_scope.segment.value}\n\n"
        "Extract ONE claim from the page text below that names a SPECIFIC "
        "external dependency this idea requires (a payment processor, a "
        "regulator, a third-party API, a supplier) together with a CITABLE "
        "PROPERTY of it: a published per-call or per-transaction price, a "
        "documented rate limit or ceiling, a licence or authorisation "
        "requirement, or a supplier's listed lead time. Put the "
        "dependency's own name/identifier in `variable` and its numeric "
        "value in `value_num` or `value_min`, with the unit in `unit`. Do "
        "NOT extract a complexity estimate, a timeline guess, or an "
        "architectural opinion (e.g. \"this will be hard to build\", "
        "\"needs a queue\", \"expect six months of engineering\") -- if the "
        "page contains only that kind of content, do not force it into a "
        "property; the claim will be rejected. The claim's `excerpt` MUST "
        "be copied verbatim from the page text below -- word for word. Set "
        "`chair` to \"dependencies\" and `source_url` to the page URL given "
        "below. If none of the assumptions already tracked for this "
        "project applies, populate `new_assumption` instead of "
        "`assumption_id`.\n\n"
        f"Page URL: {hit.url}\n"
        f"Page title: {hit.title}\n"
        f"Page text:\n{page_text}\n"
    )


async def investigate(ctx: ChairContext) -> ChairResult:
    return await run_chair(
        ctx, chair=Chair.DEPENDENCIES, provider=_PROVIDER, llm_role=_LLM_ROLE,
        build_queries=_build_queries, build_prompt=_build_prompt,
        claim_guard=_dependency_guard)
