"""The Dependencies chair. Task 4.2. PRD §6.2.

What the idea requires from the outside world: a payment processor's
published fee, a regulator's licence requirement, an API's documented rate
ceiling, a supplier's listed lead time. PRD §6.2 names this chair's real
risk explicitly: it "has the thinnest natural corpus and will drift into
opinion if unconstrained" -- "this will be hard to build" is the old
persona wearing a new badge. `_dependency_guard` below is the hard rule
that keeps it out.

**How the guard actually decides (Task 4.2 asks this to be stated
plainly):** it is two checks, both required, run as `base.run_chair`'s
`claim_guard` hook -- before `verify_claim` -- on the extracted
`ClaimRecord`:

  1. **Structural**: `variable` must be set AND at least one of
     `value_num` / `value_min` / `unit` must be set. It is deliberately NOT
     a lexical/keyword check on the `excerpt` text (e.g. "does the excerpt
     contain a capitalised word / a vendor name"), for two reasons. First,
     it would reject the brief's own canonical accepted example: PRD §6.2's
     worked "published per-call price" case is exactly
     `("stripe_api_price", "Standard pricing is 2.9% plus 30 cents per
     charge.")` -- an excerpt that names no vendor at all in its own text;
     the dependency is named by the claim's structured `variable` field
     ("stripe_api_price"), not by a proper noun inside the excerpt. Second,
     a lexical entity-in-excerpt check is the wrong direction of
     gameability: it can be satisfied by an opinion that happens to mention
     a vendor name ("Stripe will be hard to integrate.") while carrying no
     citable property at all -- exactly the failure mode this guard exists
     to close.
  2. **Grounding**: whichever of `value_num` / `value_min` / `value_max`
     ARE populated must each have their digits actually present in the
     claim's own `excerpt` text (see `_grounded`, tolerant of thousands
     separators and decimal points, via a plain digit-substring check --
     deliberately not a currency/unit parser). A structural pass alone is
     NOT enough: nothing before this fix stopped a claim like
     `variable="aws_cost_estimate", value_num=10000, unit="USD_per_month"`
     with `excerpt="AWS costs will probably balloon to over 10000 a month
     at scale."` -- an opinion, verbatim on the page, dressed in structured
     fields -- from passing both this guard and `verify_claim` (which only
     checks that the *excerpt string* appears on the fetched page; it never
     checks that a claim's numeric fields are actually the number the
     excerpt is quoting). This chair is precisely the one PRD §6.2 warns
     "drifts into opinion if unconstrained," so grounding closes that gap
     here rather than relying on the shared gate (`verify.py`) to do it --
     `verify_claim` is left unchanged; this check is Dependencies-specific.
     Requiring the extractor to fabricate a numeric field that happens to
     collide with an unrelated number already on the page is a narrower
     attack surface than free-form prompt injection, so this is
     defense-in-depth on top of the prompt's own instructions, not a
     replacement for them.

So "a specific external dependency with a citable property" is enforced as
"a variable name plus a value or unit, where any value present is the
number the excerpt actually states" -- a property, not a sentence -- and
nothing more. See the batch report for the full reasoning and the tension
between the structural check and PRD §6.2's own phrasing ("names a
domain-bearing entity"), which is not fully separable from the structural
check without rejecting the brief's own accepted example.
"""
import re

from jury.chairs.base import ChairContext, ChairResult, run_chair
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS
from jury.schemas.claim import ClaimRecord
from jury.schemas.enums import Chair
from jury.transport.protocols import SearchHit

_NUM_RUN = re.compile(r"\d+(?:\.\d+)?")


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


def _num_to_digits(value: float) -> str:
    """`value`, rendered the way it would plausibly appear on a page, then
    reduced to its bare digits. `100.0` renders as "100" (not "100.0",
    whose spurious ".0" would make a perfectly grounded whole number look
    ungrounded), while `2.9` keeps its fractional digit."""
    text = str(int(value)) if value == int(value) else repr(value)
    return _digits_only(text)


def _grounded(value: float, excerpt: str) -> bool:
    """True iff `value`'s own digit-run is one of the numbers the excerpt
    actually states -- not merely "some digit of it appears somewhere".
    Thousands separators are stripped before splitting the excerpt into
    number tokens (so "10,000" reads as one token, "10000") and each
    token's own non-digit characters (a decimal point) are then stripped
    before comparison. Deliberately not a currency/unit parser -- a
    digit-substring check after stripping separators is the brief's own
    "keep it simple" instruction."""
    value_digits = _num_to_digits(value)
    if not value_digits:
        return False
    excerpt_clean = excerpt.replace(",", "")
    for run in _NUM_RUN.findall(excerpt_clean):
        if value_digits in _digits_only(run):
            return True
    return False

_PROVIDER = CHAIR_PROVIDERS[Chair.DEPENDENCIES][0]     # "brave" -- only entry.
_LLM_ROLE = "dependencies_extract"

_BASE_QUERY_SUFFIXES = (
    "API pricing per call", "API rate limit documentation",
    "licence requirement regulator", "compliance requirement",
    "supplier lead time",
)


def _dependency_guard(claim: ClaimRecord) -> str | None:
    """PRD §6.2's hard rule: structural, then grounded. See module docstring."""
    if not claim.variable:
        return "no specific external dependency named (variable is null)"
    if claim.value_num is None and claim.value_min is None and claim.unit is None:
        return ("no citable property on the named dependency "
                "(no value_num/value_min/unit) -- an opinion, not a property")

    for field_name, value in (("value_num", claim.value_num),
                              ("value_min", claim.value_min),
                              ("value_max", claim.value_max)):
        if value is not None and not _grounded(value, claim.excerpt):
            return (f"{field_name}={value!r} is not grounded in the excerpt's "
                    "own text -- a citable property must be a figure the "
                    "page actually states, not a structured field pinned "
                    "onto an opinion")
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
