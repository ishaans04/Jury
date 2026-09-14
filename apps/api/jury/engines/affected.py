"""Affected-only recompute closure. Task 6.3. PRD §7.10, spec §26.5.

A return-visit result logs against exactly ONE assumption. Re-running the
whole graph for that (chairs, search, cross-exam) would be both wasteful and
wrong -- Spec §26.5 asks for affected-only recompute instead, "with a manual
full re-run available" for when the founder actually wants one.

This module answers a single, pure question: given the one assumption a
logged result just changed, what downstream work does that imply?

  - `assumptions`: the changed assumption itself (trivially affected).
  - `parameters`: exactly the economics parameters currently bound to THAT
    assumption -- a parameter bound to a different assumption did not move,
    so it is deliberately excluded (an unrelated founder guess about
    `delivery_cost` is untouched by a result about `price_monthly`).
  - `recompute_economics`: True only when a parameter actually moved. An
    assumption bound to no parameter (still under investigation, or simply
    never fed the solver) has nothing for the solver to re-derive from, so
    re-solving would be pure waste -- correctly skipped.
  - `recompute_verdict`: always True. Evidence Confidence and the gate are
    functions of every assumption's status (`jury.engines.scoring`), so ANY
    one assumption's status moving can move the verdict, regardless of
    whether economics was touched at all.

Pure: no I/O, no randomness, no clock. `jury/engines/` imports only
`jury.schemas` (spec §6); `tests/engines/test_purity.py` is the boundary
test that enforces it, and this module deliberately imports nothing at all
beyond the stdlib to trivially satisfy it.
"""
from dataclasses import dataclass


@dataclass(slots=True)
class AffectedSet:
    assumptions: set[str]
    parameters: set[str]
    recompute_economics: bool
    recompute_verdict: bool


def affected_closure(changed_assumption_id: str, *, parameter_bindings: dict[str, str],
                     sensitivity: list[dict]) -> AffectedSet:
    """The transitive downstream set of one assumption's change.

    `sensitivity` is accepted (and not yet consulted) because a caller
    re-running the affected economics/verdict work needs it in hand anyway
    (`jury.graph.rerun.rerun_affected` reads it straight from the same
    latest `model_run` this function's `parameter_bindings` came from); this
    function itself only needs `parameter_bindings` to answer WHAT is
    affected, not WHICH ORDER to touch it in.
    """
    del sensitivity

    parameters = {variable for variable, assumption_id in parameter_bindings.items()
                 if assumption_id == changed_assumption_id}

    return AffectedSet(
        assumptions={changed_assumption_id},
        parameters=parameters,
        recompute_economics=bool(parameters),
        recompute_verdict=True,
    )
