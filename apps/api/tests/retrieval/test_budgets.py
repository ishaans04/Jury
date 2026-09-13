from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS, BudgetLedger
from jury.schemas.enums import Chair
from jury.transport.kv import MemoryKV


def test_chair_budgets_match_the_prd_table():
    assert CHAIR_BUDGETS == {Chair.MARKET: 8, Chair.CUSTOMER: 8, Chair.PRECEDENT: 10,
                             Chair.DEPENDENCIES: 6, Chair.ECONOMICS: 3}


def test_the_budgets_sum_to_the_global_cap_of_35():
    """PRD §17.2: 35 search queries across all chairs."""
    assert sum(CHAIR_BUDGETS.values()) == 35


def test_every_chair_has_at_least_one_provider():
    assert set(CHAIR_PROVIDERS) == set(Chair)
    assert all(CHAIR_PROVIDERS[c] for c in Chair)


def test_customer_routes_to_keyless_hn_so_it_works_without_credentials():
    """Spec §3.1: HN Algolia is keyless and unlimited."""
    assert "hn" in CHAIR_PROVIDERS[Chair.CUSTOMER]


def test_precedent_routes_to_wayback_for_death_verification():
    """PRD §16.7: 'the single highest-value retrieval trick in the product'."""
    assert "wayback" in CHAIR_PROVIDERS[Chair.PRECEDENT]


def test_precedent_routes_to_exa_for_find_similar():
    assert "exa" in CHAIR_PROVIDERS[Chair.PRECEDENT]


async def test_a_chair_cannot_exceed_its_budget():
    ledger = BudgetLedger(MemoryKV(), run_id="r1")
    spent = [await ledger.spend(Chair.ECONOMICS, "brave") for _ in range(5)]
    assert spent == [True, True, True, False, False]


async def test_budgets_are_independent_per_chair():
    ledger = BudgetLedger(MemoryKV(), run_id="r1")
    for _ in range(3):
        await ledger.spend(Chair.ECONOMICS, "brave")
    assert await ledger.spend(Chair.MARKET, "brave") is True


async def test_budgets_are_independent_per_run():
    kv = MemoryKV()
    a, b = BudgetLedger(kv, "r1"), BudgetLedger(kv, "r2")
    for _ in range(3):
        await a.spend(Chair.ECONOMICS, "brave")
    assert await b.spend(Chair.ECONOMICS, "brave") is True
