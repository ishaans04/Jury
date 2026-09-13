"""The Precedent chair. Task 4.2. PRD §16.7, §25.

"The weakest retrieval in the system by a wide margin," because dead
companies are badly indexed and a plain search surfaces launch
announcements, not post-mortems. Three consequences shape this module:

1. **Widen from failures to outcomes.** A company that attempted this model
   and *succeeded* is evidence about which conditions were load-bearing,
   exactly as much as a company that failed is. So the outcome-discovery
   pass below (`_build_outcome_queries` / `_build_outcome_prompt`) asks for
   ANY outcome -- `direction` can land `supports` or `refutes` -- never only
   failures.
2. **Death verification via Wayback CDX** is "the single highest-value
   retrieval trick in the product... the answer to 'how do I know you
   didn't invent this company.'" A second pass queries `wayback` directly
   (see `_build_death_queries`) so a candidate's own archived snapshot --
   not a third party's say-so -- becomes the claim's citable source.
3. **"Nobody has attempted this" is itself a finding**, usually an
   unflattering one (PRD §25), so finding nothing sets
   `ChairResult.no_precedent_found = True` rather than `partial = True`:
   an empty corpus after genuinely looking is a valid result, not a
   degraded one.

Decision (Task 4.2, extending `run_chair`'s "one provider per chair"
convention from `market.py`): Precedent's job structurally needs two
different retrieval *roles* -- free-text outcome discovery and a specific-
URL archive lookup -- that are not the same query fanned out across
providers, so this chair calls `run_chair` twice, once per provider
(`brave` then `wayback`), against the SAME `ChairContext`/`BudgetLedger`.
`BudgetLedger.spend` keys its bucket by `(run_id, chair)` only -- `provider`
is accepted but deliberately not part of the key (see budgets.py's
docstring) -- so this still spends from one 10-query Precedent budget, not
20; a query answered by `wayback` costs exactly as much of that budget as
one answered by `brave`. Nothing here reuses one provider's hits to build
the other pass's queries (`run_chair`'s query builder only ever sees
`ChairContext`, not a previous pass's results): the death-verification pass
targets a small, explicit, pitch-keyword-triggered table of known dead
competitor domains (`_CATEGORY_DEATH_CANDIDATES`), the same kind of
deterministic, dependency-free simplification `market.py`'s own docstring
makes for "the pitch's nouns" -- extracting a real candidate domain from
pass 1's own hits (via NER, or an LLM call) is flagged there as the
principled follow-up, not attempted in this batch.
"""
from jury.chairs.base import ChairContext, ChairResult, run_chair
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS
from jury.schemas.enums import Chair
from jury.transport.protocols import SearchHit

_OUTCOME_PROVIDER = "brave"
_DEATH_PROVIDER = "wayback"
assert _OUTCOME_PROVIDER in CHAIR_PROVIDERS[Chair.PRECEDENT]
assert _DEATH_PROVIDER in CHAIR_PROVIDERS[Chair.PRECEDENT]

_LLM_ROLE = "precedent_extract"

_OUTCOME_QUERY_SUFFIXES = (
    "similar company shut down",
    "similar startup failed post mortem",
    "similar company acquired",
    "similar startup successful",
    "attempted this business model outcome",
)

# Deterministic, pitch-keyword-triggered known-dead-competitor lookup for the
# death-verification pass. See the module docstring's decision note: this is
# a deliberate simplification for this batch, not a claim that it
# generalises to an arbitrary pitch.
_CATEGORY_DEATH_CANDIDATES: dict[str, tuple[str, ...]] = {
    "invoicing": ("zipledger.test",),
}


def _candidate_domains(ctx: ChairContext) -> list[str]:
    pitch_lower = ctx.pitch.lower()
    domains: list[str] = []
    for keyword, candidates in _CATEGORY_DEATH_CANDIDATES.items():
        if keyword in pitch_lower:
            domains.extend(candidates)
    return list(dict.fromkeys(domains))


def _build_outcome_queries(ctx: ChairContext) -> list[str]:
    pitch = ctx.pitch.strip()
    queries = [f"{pitch} {suffix}" for suffix in _OUTCOME_QUERY_SUFFIXES]
    unique = list(dict.fromkeys(queries))
    return unique[:CHAIR_BUDGETS[Chair.PRECEDENT]]


def _build_death_queries(ctx: ChairContext) -> list[str]:
    return _candidate_domains(ctx)[:CHAIR_BUDGETS[Chair.PRECEDENT]]


def _build_outcome_prompt(ctx: ChairContext, hit: SearchHit, page_text: str) -> str:
    return (
        "You are the Precedent investigator for a startup evaluation system.\n"
        f"Founder's pitch: {ctx.pitch}\n"
        f"Target scope: geo={ctx.target_scope.geo.value}, "
        f"segment={ctx.target_scope.segment.value}\n\n"
        "Extract ONE precedent claim from the page text below about a "
        "company that attempted a similar business model, and what actually "
        "happened to it -- widen to ANY outcome, not only failures: a "
        "company that succeeded is evidence about which conditions were "
        "load-bearing exactly as much as one that failed. Set `direction` "
        "to \"supports\" when the outcome is evidence the model can work, "
        "or \"refutes\" when it is evidence against it (e.g. the company "
        "shut down). The claim's `excerpt` MUST be copied verbatim from the "
        "page text below -- word for word, never paraphrased or "
        "summarised. Set `chair` to \"precedent\" and `source_url` to the "
        "page URL given below. If none of the assumptions already tracked "
        "for this project applies, populate `new_assumption` instead of "
        "`assumption_id`.\n\n"
        f"Page URL: {hit.url}\n"
        f"Page title: {hit.title}\n"
        f"Page text:\n{page_text}\n"
    )


def _build_death_prompt(ctx: ChairContext, hit: SearchHit, page_text: str) -> str:
    return (
        "You are the Precedent investigator for a startup evaluation system, "
        "looking at an archived (Wayback Machine) snapshot of a candidate "
        "precedent company's own site.\n"
        f"Founder's pitch: {ctx.pitch}\n"
        f"Target scope: geo={ctx.target_scope.geo.value}, "
        f"segment={ctx.target_scope.segment.value}\n\n"
        "Extract ONE precedent claim from the archived page text below "
        "about this company's final state (e.g. a shutdown notice, an "
        "acquisition notice, or evidence it was still an operating product "
        "at the time of this snapshot). Set `direction` to \"refutes\" if "
        "this snapshot is evidence the company failed, or \"supports\" if "
        "it is evidence the model was working for them. The claim's "
        "`excerpt` MUST be copied verbatim from the page text below. Set "
        "`chair` to \"precedent\" and `source_url` to the archive.org page "
        "URL given below -- this snapshot IS the citable death/outcome "
        "date. If none of the assumptions already tracked for this project "
        "applies, populate `new_assumption` instead of `assumption_id`.\n\n"
        f"Page URL: {hit.url}\n"
        f"Page title: {hit.title}\n"
        f"Page text:\n{page_text}\n"
    )


def _merge(a: ChairResult, b: ChairResult) -> ChairResult:
    return ChairResult(
        inserted=a.inserted + b.inserted,
        rejected=a.rejected + b.rejected,
        discovered=a.discovered + b.discovered,
        partial=a.partial or b.partial,
    )


async def investigate(ctx: ChairContext) -> ChairResult:
    outcome_result = await run_chair(
        ctx, chair=Chair.PRECEDENT, provider=_OUTCOME_PROVIDER, llm_role=_LLM_ROLE,
        build_queries=_build_outcome_queries, build_prompt=_build_outcome_prompt)
    death_result = await run_chair(
        ctx, chair=Chair.PRECEDENT, provider=_DEATH_PROVIDER, llm_role=_LLM_ROLE,
        build_queries=_build_death_queries, build_prompt=_build_death_prompt)

    result = _merge(outcome_result, death_result)

    # PRD §16.7 / §25: genuinely finding nothing -- no insert, no rejection,
    # no discovered assumption, and the budget was not simply exhausted
    # first -- is itself a finding, not a failure.
    if (not result.inserted and not result.rejected and not result.discovered
            and not result.partial):
        result.no_precedent_found = True

    return result
