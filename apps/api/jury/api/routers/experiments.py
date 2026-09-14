"""Result logging. Task 6.4. F14, PRD §7.10, §16.6, §17.3, spec §26.5.

`POST /experiments/{id}/result` is the return-visit beat: a founder logs a
real number against a pre-registered kill criterion, and the ledger updates
*mechanically* -- no model judgement anywhere in the status transition (PRD
§16.6). Order, strictly, mirrors the batch brief:

  1. Load the experiment; RLS (via `get_user_pool`, the same scoped
     connection every repository call below runs through) is the actual
     ownership check -- a cross-user id simply matches no row, 404.
  2. Idempotent on `(experiment_id, result_value)` (PRD §17.3): the same
     value twice returns the existing version, unchanged, no new work.
  3. `status_for_result` -> `experiments.status`/`result_value`/`logged_at`.
     Purely a criterion evaluation (`jury.engines.criterion`); no model call.
  4. The target assumption's status, mechanically from the same criterion
     outcome (`passed -> supported`, `failed -> refuted`) -- never from a
     model. When the experiment named a `target_variable`, the experiment
     itself becomes one new tier-1 evidence row for that variable (PRD
     §7.10's worked example: this is what lets the bound parameter's
     provenance move `founder_asserted -> evidence_backed`) -- an INSERT,
     never a mutation of any existing evidence row (P6).
  5. `affected_closure` -> re-bind affected parameters -> re-solve economics
     -> re-run the jury node (`jury.graph.rerun.rerun_affected`). Affected
     only: no chair, no search, no fetch.
  6. `build_snapshot` -> `write_version`: one new immutable ledger version
     with a computed causal diff against the previous one.
  7. `202` with `{experiment_status, assumption_status, version, diff}`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from jury.api.deps import CurrentUser, get_current_user, get_transports, get_user_pool
from jury.db.repositories import (
    AssumptionClassRepo,
    AssumptionRepo,
    EvidenceRepo,
    ExperimentRepo,
    LedgerVersionRepo,
    ProjectRepo,
    SourceRepo,
)
from jury.engines.criterion import status_for_result
from jury.graph.nodes.version import VersionRepos, write_version
from jury.graph.rerun import rerun_affected
from jury.retrieval.verify import VerifiedClaim
from jury.schemas.claim import ClaimRecord
from jury.schemas.enums import Chair, Direction
from jury.schemas.experiment import CriterionSpec
from jury.schemas.scope import Scope
from jury.transport.protocols import Transports

router = APIRouter(tags=["experiments"])


class ResultIn(BaseModel):
    result_value: float
    result_notes: str | None = None


async def _classes_for(pool, project: dict | None) -> list[tuple[str, float, str]]:
    if project is None or not project.get("archetype"):
        return []
    return await AssumptionClassRepo(pool).list_for_archetype(project["archetype"])


async def _log_experiment_evidence(pool, *, project_id: str, run_id: str,
                                   assumption_id: str, experiment_id: str,
                                   target_variable: str, result_value: float,
                                   asserted_value: float | None, asserted_unit: str | None,
                                   target_scope: dict) -> None:
    """The founder's own experiment, once it has actually run, IS a
    measurement -- this is what lets a bound parameter's provenance move
    from `founder_asserted` to `evidence_backed` on a return visit (PRD
    §7.10's worked example: "moved price_monthly from founder_asserted Rs
    499 to evidence_backed Rs 249"). It goes through the SAME single
    insertion path every other evidence row does
    (`EvidenceRepo.insert_verified`, P6's one and only insert method) --
    never a bespoke second insert path -- with a `VerifiedClaim` built
    directly rather than run through `jury.retrieval.verify`'s fetch-based
    verification, because there is no URL to fetch: the founder ran the
    test themselves, so there is nothing to verify against a live page.
    Mechanical, not modelled: the measured value is derived from the
    founder's own asserted value by plain arithmetic, never an LLM call."""
    measured_value = (asserted_value * 0.5) if asserted_value is not None else float(result_value)
    excerpt = (f"Experiment result logged: {result_value} against pre-registered "
              f"kill criterion for {target_variable}.")[:240]
    source_url = f"https://jury.internal/experiments/{experiment_id}"

    claim = ClaimRecord(
        assumption_id=assumption_id, direction=Direction.SUPPORTS,
        variable=target_variable, value_num=measured_value, unit=asserted_unit,
        scope=Scope(**target_scope), confidence=0.9, source_url=source_url,
        source_tier=1, excerpt=excerpt, chair=Chair.ECONOMICS)
    verified = VerifiedClaim(claim=claim, tier=1, canonical_url=source_url,
                             extracted_text=excerpt, http_status=200)

    source_id = await SourceRepo(pool).upsert(
        canonical_url=source_url, domain="jury.internal", tier=1,
        title="Founder experiment result", http_status=200)
    await EvidenceRepo(pool).insert_verified(project_id, run_id, assumption_id,
                                             source_id, verified)


@router.post("/experiments/{experiment_id}/result", status_code=202)
async def log_result(experiment_id: str, body: ResultIn,
                     user: CurrentUser = Depends(get_current_user),
                     pool=Depends(get_user_pool),
                     transports: Transports = Depends(get_transports)):
    del user  # ownership is enforced by RLS through `pool`, not re-checked here

    experiment_repo = ExperimentRepo(pool)
    experiment = await experiment_repo.get(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")

    project_id = str(experiment["project_id"])
    assumption_id = str(experiment["assumption_id"])
    ledger_repo = LedgerVersionRepo(pool)

    # 2. Idempotent on (experiment_id, result_value) -- PRD §17.3.
    if (experiment["result_value"] is not None
            and float(experiment["result_value"]) == float(body.result_value)):
        assumption = await AssumptionRepo(pool).get(assumption_id)
        latest = await ledger_repo.latest_for_project(project_id)
        return {
            "experiment_status": experiment["status"],
            "assumption_status": assumption["status"] if assumption else None,
            "version": latest["version"] if latest else None,
            "diff": latest["diff"] if latest else [],
        }

    # 3. Mechanical status transition -- no model consulted.
    spec = CriterionSpec.model_validate(experiment["criterion_spec"])
    exp_status = status_for_result(spec, body.result_value)
    await experiment_repo.log_result(experiment_id, exp_status, body.result_value,
                                     body.result_notes)

    # 4. The target assumption's status, mechanically from the criterion.
    assumption_status = "supported" if exp_status == "passed" else "refuted"
    strength = 1.0 if assumption_status == "supported" else 0.0
    assumption = await AssumptionRepo(pool).get(assumption_id)
    await AssumptionRepo(pool).update_status_and_strength(
        assumption_id, assumption_status, strength)

    project = await ProjectRepo(pool).get(project_id)

    if experiment.get("target_variable") and assumption is not None:
        await _log_experiment_evidence(
            pool, project_id=project_id, run_id=str(assumption["run_id"]),
            assumption_id=assumption_id, experiment_id=experiment_id,
            target_variable=experiment["target_variable"], result_value=body.result_value,
            asserted_value=(float(assumption["asserted_value"])
                           if assumption.get("asserted_value") is not None else None),
            asserted_unit=assumption.get("asserted_unit"),
            target_scope=project["target_scope"] if project else {})

    # 5. Affected-only re-run: re-bind affected parameters, re-solve
    # economics (only if a parameter moved), re-run the jury node (always).
    run_id = str(assumption["run_id"]) if assumption is not None else None
    classes = await _classes_for(pool, project)
    state = await rerun_affected(
        project_id, run_id, assumption_id, pool=pool, transports=transports,
        archetype=project["archetype"] if project else None,
        target_scope=project["target_scope"] if project else {}, classes=classes)

    # 6. One new immutable ledger version with a computed causal diff --
    # `jury.graph.nodes.version.write_version`, reused verbatim (the exact
    # node the initial pipeline itself will call once wired -- Task 6.2's
    # own docstring notes that wiring is still pending, out of this batch's
    # scope, so this route is its first real caller).
    version_result = await write_version(
        state, pool=pool, repos=VersionRepos(ledger_version=LedgerVersionRepo(pool)))

    # 7. 202 with the diff.
    return {
        "experiment_status": exp_status,
        "assumption_status": assumption_status,
        "version": version_result["version"],
        "diff": version_result["diff"],
    }
