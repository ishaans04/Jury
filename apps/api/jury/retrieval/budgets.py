"""Per-chair search routing and enforced budgets. PRD §16.1, §17.2.

PRD §11.2 decision 11's reason for keeping the chairs on distinct corpora:
"Precedent needs semantic find-similar (Exa); Market needs an independent
index and direct page fetches (Brave); Customer needs domain APIs. Neither
substitutes for the other." Five personas sharing one search index would
converge on the same blind spots; five distinct corpora do not.

Budgets are hard caps, not advice: a chair that exhausts its budget is
marked `partial` (Phase 4), which lowers the run's coverage score and
correctly pushes the final verdict toward "insufficient evidence to rule."
Degrading honestly, rather than over-querying past the published cap, is the
designed behaviour.
"""
from jury.schemas.enums import Chair
from jury.transport.protocols import KV

# PRD §17.2: 35 search queries across all chairs, split per the PRD table.
# A test (test_the_budgets_sum_to_the_global_cap_of_35) asserts the sum
# stays in lockstep with that separately published total.
CHAIR_BUDGETS: dict[Chair, int] = {
    Chair.MARKET: 8,
    Chair.CUSTOMER: 8,
    Chair.PRECEDENT: 10,
    Chair.DEPENDENCIES: 6,
    Chair.ECONOMICS: 3,
}

# Keyless providers ("hn", "wayback") are listed first only where it matters
# for a chair's ability to function before any credential exists (spec
# §3.1); order otherwise carries no meaning to the ledger.
#
# NOTE: "producthunt" appears here (Precedent) but LiveSearchClient in
# search.py implements only the seven providers named in the batch brief's
# interfaces section (brave, tavily, exa, hn, reddit, wayback, playstore) --
# "producthunt" is not one of them, even though `settings.producthunt_token`
# exists. That looks like a real gap in the brief rather than an intentional
# omission (see search.py's module docstring for how it's handled: routing
# to an unimplemented provider degrades to no results, the same as routing
# to one with a missing key, rather than raising).
CHAIR_PROVIDERS: dict[Chair, tuple[str, ...]] = {
    Chair.MARKET:       ("brave", "tavily"),
    Chair.CUSTOMER:     ("hn", "reddit", "playstore", "brave"),
    Chair.PRECEDENT:    ("exa", "brave", "wayback", "producthunt"),
    Chair.DEPENDENCIES: ("brave",),
    Chair.ECONOMICS:    ("brave",),
}

_BUDGET_WINDOW_S = 3600


class BudgetLedger:
    """One instance tracks all five chairs' spend for a single run.

    Each chair's counter is independent (its own KV bucket key) and each
    run's counters are independent (`run_id` is part of every key), so two
    chairs in the same run, or the same chair across two runs, never share
    a budget.

    Concurrency: `spend` does nothing but forward to `kv.incr_bucket`, so it
    inherits whatever atomicity guarantee the KV backend gives that call --
    see the module docstring in the batch report for why that is safe under
    Phase 4's concurrent chair fan-out (the same TOCTOU concern the LLM
    gateway's `_reserve_budget` documents for its own call cap).
    """

    def __init__(self, kv: KV, run_id: str) -> None:
        self._kv = kv
        self._run_id = run_id

    async def spend(self, chair: Chair, provider: str) -> bool:
        """Attempt to spend one query of `chair`'s budget. Returns False once
        the budget is exhausted -- the caller must stop querying for that
        chair, not retry.

        `provider` is accepted because the interface requires it, but it is
        deliberately NOT part of the bucket key: PRD §17.2 frames the cap as
        one query budget per chair ("8 for Market", etc.), not one budget
        per chair-provider pair, so which of a chair's routed providers
        absorbs a given query does not change how much of its budget is
        left.
        """
        del provider  # not part of the key; see docstring
        key = f"budget:{self._run_id}:{chair}"
        return await self._kv.incr_bucket(key, limit=CHAIR_BUDGETS[chair],
                                          window_s=_BUDGET_WINDOW_S)
