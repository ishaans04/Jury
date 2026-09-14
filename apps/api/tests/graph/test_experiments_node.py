"""jury.graph.nodes.experiments. Task 5.5. PRD §16.6.

Uses the rollback `pool` fixture, same reasoning as the other Batch T node
test modules.
"""
import pytest

from jury.db.repositories import ExperimentRepo
from jury.graph.nodes.experiments import ExperimentsRepos, plan_experiments

pytestmark = pytest.mark.asyncio


async def _seed_project(pool, *, suffix="") -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'expnode-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{}') returning id",
                (user_id, "expco" + suffix))
            project_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', %s) returning id",
                (project_id, user_id, "xt" + suffix))
            run_id = (await cur.fetchone())[0]
    return {"project_id": str(project_id), "run_id": str(run_id)}


async def _seed_assumption(pool, seed, *, criticality="medium") -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into assumptions (project_id, run_id, statement, origin, "
                "criticality, uncertainty, falsifiability) "
                "values (%s, %s, 'a statement', 'founder', %s, 'uncertain', "
                "'testable_now') returning id",
                (seed["project_id"], seed["run_id"], criticality))
            return str((await cur.fetchone())[0])


def _repos(pool) -> ExperimentsRepos:
    return ExperimentsRepos(experiment=ExperimentRepo(pool))


async def test_only_founder_asserted_parameters_become_experiments(pool):
    seed = await _seed_project(pool, suffix="-a")
    evidence_backed_id = await _seed_assumption(pool, seed)
    founder_id = await _seed_assumption(pool, seed)
    model_run = {
        "parameters": {
            "price_monthly": {"assumption_id": evidence_backed_id,
                              "provenance": "evidence_backed"},
            "take_rate": {"assumption_id": founder_id, "provenance": "founder_asserted"},
        },
        "sensitivity": [
            {"variable": "price_monthly", "elasticity": 0.9,
             "provenance": "evidence_backed"},
            {"variable": "take_rate", "elasticity": 0.5, "provenance": "founder_asserted"},
        ],
        "breakpoints": [],
    }
    out = await plan_experiments({"project_id": seed["project_id"], "run_id": seed["run_id"],
                                  "model_run": model_run}, repos=_repos(pool))
    variables = {e["target_variable"] for e in out["experiments"]}
    assert variables == {"take_rate"}


async def test_every_experiment_has_a_non_null_criterion_spec(pool):
    seed = await _seed_project(pool, suffix="-b")
    founder_id = await _seed_assumption(pool, seed)
    model_run = {
        "parameters": {"take_rate": {"assumption_id": founder_id,
                                     "provenance": "founder_asserted"}},
        "sensitivity": [{"variable": "take_rate", "elasticity": 0.5,
                        "provenance": "founder_asserted"}],
        "breakpoints": [],
    }
    out = await plan_experiments({"project_id": seed["project_id"], "run_id": seed["run_id"],
                                  "model_run": model_run}, repos=_repos(pool))
    assert out["experiments"]
    for e in out["experiments"]:
        assert e["kill_criterion"]
        assert e["criterion_spec"]


async def test_priority_follows_sensitivity_rank(pool):
    seed = await _seed_project(pool, suffix="-c")
    a1 = await _seed_assumption(pool, seed)
    a2 = await _seed_assumption(pool, seed)
    model_run = {
        "parameters": {
            "take_rate": {"assumption_id": a1, "provenance": "founder_asserted"},
            "price_monthly": {"assumption_id": a2, "provenance": "founder_asserted"},
        },
        "sensitivity": [
            {"variable": "take_rate", "elasticity": 0.2, "provenance": "founder_asserted"},
            {"variable": "price_monthly", "elasticity": 0.95,
             "provenance": "founder_asserted"},
        ],
        "breakpoints": [],
    }
    out = await plan_experiments({"project_id": seed["project_id"], "run_id": seed["run_id"],
                                  "model_run": model_run}, repos=_repos(pool))
    ranked = sorted(out["experiments"], key=lambda e: e["priority"])
    assert ranked[0]["target_variable"] == "price_monthly"   # highest |elasticity|


async def test_modelled_thresholds_reach_the_persisted_criterion_spec(pool):
    """P9 / the batch's own extra-scrutiny requirement: without `modelled=`
    plumbed through, delivery_cost's supplier_quote experiment would be
    skipped entirely -- generate_experiments treats a missing modelled value
    as an honest absence, never a placeholder-0 threshold."""
    seed = await _seed_project(pool, suffix="-d")
    delivery_id = await _seed_assumption(pool, seed, criticality="high")
    model_run = {
        "parameters": {"delivery_cost": {"assumption_id": delivery_id,
                                         "provenance": "founder_asserted"}},
        "sensitivity": [{"variable": "delivery_cost", "elasticity": 0.6,
                        "provenance": "founder_asserted"}],
        "breakpoints": [{"variable": "delivery_cost", "threshold": 37.5,
                        "direction": "above", "unit": "currency_per_txn",
                        "output": "contribution_margin", "sentence": "x"}],
    }
    out = await plan_experiments({"project_id": seed["project_id"], "run_id": seed["run_id"],
                                  "model_run": model_run}, repos=_repos(pool))
    supplier = next(e for e in out["experiments"] if e["method"] == "supplier_quote")
    assert supplier["criterion_spec"]["threshold"] == pytest.approx(37.5)

    rows = await ExperimentRepo(pool).list_for_project(seed["project_id"])
    persisted = next(r for r in rows if r["method"] == "supplier_quote")
    assert float(persisted["criterion_spec"]["threshold"]) == pytest.approx(37.5)
    assert persisted["criterion_spec"]["threshold"] != 0.0


async def test_run_status_is_marked_complete(pool):
    seed = await _seed_project(pool, suffix="-e")
    out = await plan_experiments({"project_id": seed["project_id"], "run_id": seed["run_id"],
                                  "model_run": {}}, repos=_repos(pool))
    assert out["run_status"] == "complete"
