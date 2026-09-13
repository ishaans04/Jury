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
# Every provider named below must be one `LiveSearchClient` (search.py) can
# actually service -- test_every_routed_provider_is_implemented enforces
# this so the table and the implementation cannot silently drift apart.
#
# "producthunt" deliberately does NOT appear here (Precedent), even though
# `settings.producthunt_token` exists and an earlier draft of this table
# routed to it. Code review caught that an unimplemented provider in this
# table is not harmless: BudgetLedger.spend has no way to know a routed
# provider is a permanent no-op, so Phase 4's chair loop would spend one of
# Precedent's 10 queries on a call that degrades to `search()` returning []
# no matter what -- silently shrinking Precedent's real budget to 9 of 10.
# Precedent is already the weakest retrieval chair in the system by a wide
# margin (PRD framing); it can least afford to lose a tenth of its queries
# to a call that can never return evidence. An unimplemented entry in a
# routing table is a promise the code cannot keep, so it is left out until
# `LiveSearchClient` actually implements a Product Hunt provider -- at which
# point it belongs both here and in `IMPLEMENTED_PROVIDERS` (search.py).
CHAIR_PROVIDERS: dict[Chair, tuple[str, ...]] = {
    Chair.MARKET:       ("brave", "tavily"),
    Chair.CUSTOMER:     ("hn", "reddit", "playstore", "brave"),
    Chair.PRECEDENT:    ("exa", "brave", "wayback"),
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
