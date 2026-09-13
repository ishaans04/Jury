"""The Market chair. Task 3.7. PRD §6.

Investigates competitors, pricing, market structure and demand signal.
Queries are templated from the pitch plus the founder's own asserted
variables (PRD §6: "a price_monthly assertion generates a '<category>
pricing' query") -- which is what lets R3 (jury/engines/conflict.py) later
catch a founder's asserted price contradicting what the market actually
charges. Everything else -- budget spending, search, fetch, extraction,
verification, persistence, tracing -- is `jury.chairs.base.run_chair`; this
module supplies only the query strategy and the extraction prompt.

Decision: "the pitch's nouns" (brief's phrasing) is not full NLP noun
extraction here -- `ctx.pitch` is used verbatim as the category phrase in
every query template. That keeps query generation deterministic and
dependency-free; a later batch can replace `_build_queries` with a real noun
extractor without touching anything else in this module or in `base.py`.
"""
from jury.chairs.base import ChairContext, ChairResult, run_chair
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS
from jury.schemas.enums import Chair
from jury.transport.protocols import SearchHit

_PROVIDER = CHAIR_PROVIDERS[Chair.MARKET][0]     # "brave" -- see base.py's
                                                   # module docstring for why
                                                   # this chair uses only one
                                                   # of its routed providers.
_LLM_ROLE = "market_extract"

# PRD §6's four topics a Market claim can be about: competitor pricing pages,
# plan comparisons, competitor counts, funding facts, launch dates.
_BASE_QUERY_SUFFIXES = ("pricing", "plans comparison", "competitors", "funding",
                        "launch date")

# A founder's own asserted_variable name maps to the query it should provoke.
# Only variables that map to one of PRD §6's topics are listed; an assumption
# whose asserted_variable has no entry here contributes no extra query (the
# five base queries above already cover the chair's remit).
_VARIABLE_QUERY_TEMPLATES = {
    "price_monthly": "pricing",
    "price_annual": "pricing",
}


def _build_queries(ctx: ChairContext) -> list[str]:
    pitch = ctx.pitch.strip()
    queries = [f"{pitch} {suffix}" for suffix in _BASE_QUERY_SUFFIXES]
    for assumption in ctx.assumptions:
        suffix = _VARIABLE_QUERY_TEMPLATES.get(assumption.asserted_variable or "")
        if suffix:
            queries.append(f"{pitch} {suffix}")
    # De-duplicate (an assumption's template commonly repeats a base query --
    # price_monthly's "pricing" is already query #1) while preserving order,
    # then cap at the chair's own budget so a normal run never manufactures
    # more queries than it could ever spend.
    unique = list(dict.fromkeys(queries))
    return unique[:CHAIR_BUDGETS[Chair.MARKET]]


def _build_prompt(ctx: ChairContext, hit: SearchHit, page_text: str) -> str:
    return (
        "You are the Market investigator for a startup evaluation system.\n"
        f"Founder's pitch: {ctx.pitch}\n"
        f"Target scope: geo={ctx.target_scope.geo.value}, "
        f"segment={ctx.target_scope.segment.value}\n\n"
        "Extract ONE market claim (competitor pricing, plan structure, "
        "competitor count, funding fact, or launch date) from the page text "
        "below that bears on evaluating this pitch. The claim's `excerpt` "
        "MUST be copied verbatim from the page text -- word for word, never "
        "paraphrased or summarised. Set `chair` to \"market\" and "
        "`source_url` to the page URL given below. If none of the assumptions "
        "already tracked for this project applies, populate `new_assumption` "
        "instead of `assumption_id`.\n\n"
        f"Page URL: {hit.url}\n"
        f"Page title: {hit.title}\n"
        f"Page text:\n{page_text}\n"
    )


async def investigate(ctx: ChairContext) -> ChairResult:
    return await run_chair(
        ctx, chair=Chair.MARKET, provider=_PROVIDER, llm_role=_LLM_ROLE,
        build_queries=_build_queries, build_prompt=_build_prompt)
