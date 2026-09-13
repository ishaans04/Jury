"""The Customer chair. Task 4.2. PRD §6, §18.

Investigates pain, willingness to pay, objections and feature-gap patterns
in the founder's own target users' words. Sources: Reddit, HN Algolia,
Google Play reviews, App Store listings (`CHAIR_PROVIDERS[Chair.CUSTOMER]`).

Decision (mirrors `jury.chairs.base`'s "one search provider per chair"
choice for Market): this chair uses only its FIRST routed provider, `hn` --
not because HN is the richest corpus, but because it is the only one of the
four that needs no credential at all (spec §3.1). PRD §18's degrade
contract ("degrade to HN Algolia, which is keyless and unlimited") is a
requirement on the whole chair, not just a fallback path, so the base
pipeline is driven by `hn` unconditionally rather than probing Reddit first
and falling back -- a credentialed deployment gets Reddit/Play Store
evidence in a later batch by adding a second `run_chair` pass (precisely
the shape Precedent uses in this same batch for its wayback pass), not by
making this chair's only pass conditional on which keys happen to be set.
This is what makes `test_customer_works_with_no_reddit_credentials` true by
construction rather than by a runtime credential probe: Reddit is simply
never called from this module.
"""
from jury.chairs.base import ChairContext, ChairResult, run_chair
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS
from jury.schemas.enums import Chair
from jury.transport.protocols import SearchHit

_PROVIDER = CHAIR_PROVIDERS[Chair.CUSTOMER][0]     # "hn" -- keyless, see module docstring.
_LLM_ROLE = "customer_extract"

# PRD §6's shapes a Customer claim can take: quoted pain language, WTP
# evidence, refusal evidence ("I cancelled because..."), feature-gap patterns
# ("I switched to X because it has...").
_BASE_QUERY_SUFFIXES = (
    "complaints", "too expensive", "cancelled subscription",
    "missing feature", "switched to alternative",
)


def _build_queries(ctx: ChairContext) -> list[str]:
    pitch = ctx.pitch.strip()
    queries = [f"{pitch} {suffix}" for suffix in _BASE_QUERY_SUFFIXES]
    unique = list(dict.fromkeys(queries))
    return unique[:CHAIR_BUDGETS[Chair.CUSTOMER]]


def _build_prompt(ctx: ChairContext, hit: SearchHit, page_text: str) -> str:
    return (
        "You are the Customer investigator for a startup evaluation system.\n"
        f"Founder's pitch: {ctx.pitch}\n"
        f"Target scope: geo={ctx.target_scope.geo.value}, "
        f"segment={ctx.target_scope.segment.value}\n\n"
        "Extract ONE customer claim from the forum post below: real users' "
        "quoted pain language, willingness-to-pay evidence, refusal evidence "
        "(why someone would not pay or cancelled), or a feature-gap pattern "
        "(a specific thing users say a competitor lacks or has). The claim's "
        "`excerpt` MUST be copied verbatim from the page text below -- word "
        "for word, never paraphrased or summarised. Do not report your own "
        "opinion of the idea; only report what the quoted users actually "
        "said. Set `chair` to \"customer\" and `source_url` to the page URL "
        "given below. If none of the assumptions already tracked for this "
        "project applies, populate `new_assumption` instead of "
        "`assumption_id`.\n\n"
        f"Page URL: {hit.url}\n"
        f"Page title: {hit.title}\n"
        f"Page text:\n{page_text}\n"
    )


async def investigate(ctx: ChairContext) -> ChairResult:
    return await run_chair(
        ctx, chair=Chair.CUSTOMER, provider=_PROVIDER, llm_role=_LLM_ROLE,
        build_queries=_build_queries, build_prompt=_build_prompt)
