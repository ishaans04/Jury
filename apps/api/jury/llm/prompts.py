"""Prompt templates for the graph nodes that make structured LLM calls.

Kept out of the node modules so the extraction prompt's data contract is
visible in exactly one place: **the belief-class checklist is embedded
verbatim from the `classes` argument -- never regenerated, reworded, or
invented here.** P4 (PRD): coverage is measured against a hand-seeded
external checklist (`assumption_classes`, db/seed/001_assumption_classes.sql),
never against categories the model invents for itself, or the coverage score
becomes self-graded. This module's job is only to hand that checklist to the
model as data and ask it to classify against it; `jury.graph.nodes.coverage`
computes silence afterward against the exact same list.
"""
from jury.schemas.enums import Archetype, Geo, Segment


def archetype_detection_prompt(pitch: str) -> str:
    archetypes = ", ".join(a.value for a in Archetype)
    geos = ", ".join(g.value for g in Geo)
    segments = ", ".join(s.value for s in Segment)
    return (
        "You are classifying a startup pitch into ONE business archetype for "
        "a due-diligence system.\n\n"
        f"Pitch:\n{pitch}\n\n"
        f"Choose exactly one archetype from: {archetypes}.\n\n"
        "Also infer the single most likely target market this pitch is "
        "actually written for -- spec section 26.2: the founder chooses the "
        "target scope explicitly at an intake form later, and this inferred "
        "scope only pre-fills that form as a default the founder can "
        "override. Infer it literally from the pitch's own wording (who it "
        "names as the customer, what geography or currency it mentions), "
        "not from whatever market you judge to be 'best'.\n"
        f"geo must be one of: {geos}.\n"
        f"segment must be one of: {segments}.\n\n"
        "Give a confidence between 0 and 1 for the archetype call and a "
        "one-sentence reasoning for both the archetype and the scope."
    )


def assumption_extraction_prompt(pitch: str, classes: list[tuple[str, float, str]]) -> str:
    checklist = "\n".join(f"- {key}: {question}" for key, _weight, question in classes)
    return (
        "You are extracting the falsifiable assumptions a founder's pitch "
        "depends on, for a due-diligence system. A falsifiable assumption is "
        "a single-clause, checkable belief -- not a goal, not a feature "
        "description, and not a compound sentence joining two separate "
        "claims.\n\n"
        f"Founder's pitch:\n{pitch}\n\n"
        "Below is the FIXED checklist of belief-classes this business "
        "archetype is judged against. This checklist is external reference "
        "data -- it was NOT produced by you, and you must NOT invent, "
        "rename, merge, or add any class of your own. Classify every "
        "assumption you extract against the closest class_key on this list "
        "when one genuinely fits; set class_key to null when none does. It "
        "is normal and expected for several classes below to end up with no "
        "assumption at all -- leave those classes alone rather than "
        "fabricating an assumption just to cover one.\n\n"
        f"{checklist}\n\n"
        "Extract at least 8 distinct assumptions implied by what the pitch "
        "states AND by what it conspicuously leaves unaddressed. Each "
        "assumption must:\n"
        "- be exactly ONE sentence, single-clause, ending in exactly one "
        "  period -- never two independent claims joined by 'and then', a "
        "  semicolon, or otherwise stitched together.\n"
        "- state a belief the FOUNDER holds (origin='founder'), not a "
        "  finding from outside research; discovered_by must be null.\n"
        "- be scored on all three axes: criticality (blocking/high/medium/"
        "  low), uncertainty (unknown/uncertain/likely/established), and "
        "  falsifiability (testable_now/testable_costly/untestable).\n"
        "- if the pitch states a concrete number for that belief (a price, a "
        "  percentage, a duration, a count), capture it precisely as "
        "  asserted_variable (a short snake_case name for the quantity), "
        "  asserted_value (the number itself), and asserted_unit -- never "
        "  drop a number the founder actually stated.\n"
    )
