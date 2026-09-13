"""Coverage-gap report. Task 4.1. F6, PRD §7.3, §22.

"Silence is a finding, and it is usually the first thing worth showing the
founder" (PRD §7.3). `coverage_gaps` is a pure function on purpose: coverage
must be measured against the hand-seeded `assumption_classes` checklist
passed in as `classes`, never against anything this module or the model
invents, or the score would be self-graded and meaningless (P4).
"""


def coverage_gaps(classes: list[tuple[str, float, str]],
                  assumptions: list[dict]) -> list[dict]:
    """Every class in `classes` that no assumption in `assumptions` names,
    ordered so the founder sees the highest-stakes silences first.

    `classes` entries are `(key, crit_weight, question)`. Ordering is by
    `-crit_weight` (blocking silences before high, high before medium/low)
    and then by `key` ascending as the tiebreaker -- `key` is a stable,
    already-unique string, so two classes sharing a weight sort the same way
    on every call and every run, never by insertion order or dict/set
    iteration, which Python does not guarantee across runs for arbitrary
    objects.
    """
    covered = {a.get("class_key") for a in assumptions if a.get("class_key")}
    gaps = [
        {"key": key, "crit_weight": weight, "question": question}
        for key, weight, question in classes
        if key not in covered
    ]
    gaps.sort(key=lambda g: (-g["crit_weight"], g["key"]))
    return gaps
