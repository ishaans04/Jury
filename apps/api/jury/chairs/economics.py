"""The Economics chair. Task 4.2. PRD §6.

Benchmark lookups only -- an industry-average CAC, churn rate, gross margin
or take rate, each a typed claim with a citable source. This chair does
NOT solve the founder's unit-economics model; combining these benchmarks
with the founder's own asserted numbers into a viable/non-viable verdict is
`jury.engines.economics`, arriving in Phase 5. Reflecting that in the
budget table (`CHAIR_BUDGETS[Chair.ECONOMICS] == 3`, the smallest of the
five): there is no fan-out to do here, only a handful of named benchmarks
to look up.
"""
from jury.chairs.base import ChairContext, ChairResult, run_chair
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS
from jury.schemas.enums import Chair
from jury.transport.protocols import SearchHit

_PROVIDER = CHAIR_PROVIDERS[Chair.ECONOMICS][0]     # "brave" -- only entry.
_LLM_ROLE = "economics_extract"

# PRD §6's benchmark figures this chair looks up -- deliberately narrow: it
# is a lookup pass, not a modelling pass.
_BASE_QUERY_SUFFIXES = (
    "industry average CAC benchmark",
    "industry average churn rate benchmark",
    "industry average gross margin benchmark",
)


def _build_queries(ctx: ChairContext) -> list[str]:
    pitch = ctx.pitch.strip()
    queries = [f"{pitch} {suffix}" for suffix in _BASE_QUERY_SUFFIXES]
    unique = list(dict.fromkeys(queries))
    return unique[:CHAIR_BUDGETS[Chair.ECONOMICS]]


def _build_prompt(ctx: ChairContext, hit: SearchHit, page_text: str) -> str:
    return (
        "You are the Economics investigator for a startup evaluation "
        "system.\n"
        f"Founder's pitch: {ctx.pitch}\n"
        f"Target scope: geo={ctx.target_scope.geo.value}, "
        f"segment={ctx.target_scope.segment.value}\n\n"
        "Extract ONE benchmark claim from the page text below: an industry-"
        "average figure (e.g. CAC, churn rate, gross margin, take rate, "
        "LTV) for this category. Record ONLY the benchmark figure itself in "
        "`value_num`/`value_min`/`value_max` and `unit` -- do not compute or "
        "opine on whether the founder's own numbers are viable; a later "
        "deterministic engine does that comparison, not you. The claim's "
        "`excerpt` MUST be copied verbatim from the page text below -- word "
        "for word, never paraphrased or summarised. Set `chair` to "
        "\"economics\" and `source_url` to the page URL given below. If "
        "none of the assumptions already tracked for this project applies, "
        "populate `new_assumption` instead of `assumption_id`.\n\n"
        f"Page URL: {hit.url}\n"
        f"Page title: {hit.title}\n"
        f"Page text:\n{page_text}\n"
    )


async def investigate(ctx: ChairContext) -> ChairResult:
    return await run_chair(
        ctx, chair=Chair.ECONOMICS, provider=_PROVIDER, llm_role=_LLM_ROLE,
        build_queries=_build_queries, build_prompt=_build_prompt)
