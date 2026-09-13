from pydantic import BaseModel, Field

from jury.llm.structured import schema_prompt_block, structured_many, structured_report
from jury.schemas.enums import Direction
from jury.schemas.scope import Scope
from jury.transport.protocols import LLMResponse


class Tiny(BaseModel):
    name: str
    count: int = Field(ge=0)


class WithEnumAndScope(BaseModel):
    """Shaped like the real ClaimRecord: an enum field and a nested-object
    field (ClaimRecord has `direction: Direction`, `chair: Chair` and
    `scope: Scope`, `new_assumption: NewAssumption | None`)."""

    direction: Direction
    scope: Scope


class Scripted:
    """Returns a scripted sequence of responses, one per call."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.prompts: list[str] = []
        self.json_modes: list[bool] = []

    async def complete(self, *, model, messages, json_mode=False, temperature=0.0):
        self.prompts.append(messages[-1]["content"])
        self.json_modes.append(json_mode)
        text = self._texts.pop(0) if self._texts else "{}"
        return LLMResponse(text=text, model=model, prompt_tokens=1, completion_tokens=1)


# ── stage 1: it just works ──────────────────────────────────────────────────
async def test_valid_first_response_needs_no_repair():
    client = Scripted('{"name":"a","count":2}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=2)
    assert rep.stages == ["initial"]


async def test_json_mode_is_always_enabled():
    """PRD §15.3 mitigation 1: JSON mode on EVERY structured call."""
    client = Scripted('{"name":"a","count":2}')
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert client.json_modes == [True]


async def test_the_schema_is_embedded_in_the_prompt():
    """PRD §15.3 mitigation 2: the schema is also embedded in the prompt."""
    client = Scripted('{"name":"a","count":2}')
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert "count" in client.prompts[0] and "name" in client.prompts[0]


async def test_fenced_json_is_tolerated():
    """Small models wrap JSON in markdown fences constantly."""
    client = Scripted('```json\n{"name":"a","count":2}\n```')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=2)


async def test_prose_wrapped_json_is_extracted():
    client = Scripted('Sure! Here is the record: {"name":"a","count":2} Hope that helps.')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=2)


# ── stage 2: the repair re-prompt ───────────────────────────────────────────
async def test_invalid_then_valid_repairs_on_the_second_call():
    client = Scripted('{"name":"a","count":-1}', '{"name":"a","count":1}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=1)
    assert rep.stages == ["initial", "repair"]


async def test_the_repair_prompt_carries_the_error_and_the_offending_output():
    """PRD §15.3 mitigation 3: re-prompt with the validation error AND the
    offending output attached."""
    client = Scripted('{"name":"a","count":-1}', '{"name":"a","count":1}')
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    repair_prompt = client.prompts[1]
    assert '"count":-1' in repair_prompt.replace(" ", "")
    assert "count" in repair_prompt
    assert "greater than or equal" in repair_prompt.lower() or "ge" in repair_prompt


async def test_repair_is_attempted_exactly_once():
    client = Scripted('{"bad":1}', '{"bad":2}', '{"name":"a","count":1}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.stages.count("repair") == 1


# ── stage 3: field-split downgrade ─────────────────────────────────────────
async def test_second_failure_downgrades_to_single_field_calls():
    """PRD §15.3 mitigation 4: split one extraction into narrower single-field
    calls, which small models handle far more reliably."""
    client = Scripted('{"bad":1}', '{"still":"bad"}', '"a"', "2")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.stages == ["initial", "repair", "field_split"]
    assert rep.value == Tiny(name="a", count=2)


async def test_field_split_prompts_ask_for_one_field_each():
    client = Scripted('{"bad":1}', '{"still":"bad"}', '"a"', "2")
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    split_prompts = client.prompts[2:]
    assert len(split_prompts) == 2
    assert "name" in split_prompts[0] and "count" not in split_prompts[0]
    assert "count" in split_prompts[1]


# ── stage 4: drop the claim ────────────────────────────────────────────────
async def test_third_failure_drops_the_claim_and_returns_none():
    """PRD §15.3 mitigation 5: a dropped claim is acceptable; a malformed
    ledger row is not."""
    client = Scripted('{"bad":1}', '{"bad":2}', "nonsense", "garbage")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value is None
    assert rep.stages[-1] == "dropped"


async def test_dropping_a_claim_records_an_error_for_the_trace():
    """The error row is what makes a dropped claim visible in F17's viewer
    rather than silently vanishing."""
    client = Scripted('{"bad":1}', '{"bad":2}', "nonsense", "garbage")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.errors, "a dropped claim must carry the reason it was dropped"


async def test_a_dropped_claim_never_returns_a_partial_object():
    """A half-populated record is exactly the malformed ledger row P1 forbids."""
    client = Scripted('{"name":"a"}', '{"name":"a"}', '"a"', "not-a-number")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value is None


async def test_escalation_order_is_never_skipped():
    client = Scripted('{"bad":1}', '{"bad":2}', "x", "y")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.stages == ["initial", "repair", "field_split", "dropped"]


# ── helper ─────────────────────────────────────────────────────────────────
def test_schema_prompt_block_lists_every_field_and_its_type():
    block = schema_prompt_block(Tiny)
    assert "name" in block and "count" in block
    assert "string" in block.lower() and "integer" in block.lower()


# ── extra: nested-object and enum fields in the schema block ───────────────
# ClaimRecord (the real schema this module exists for) has an enum field
# (direction, chair) and nested-object fields (scope, new_assumption). In
# JSON-schema terms those render as `{"$ref": ...}` with no "type" key, so a
# renderer that only checks `spec.get("type")` collapses every one of them to
# "any" -- exactly the fields where an explicit list matters most. These
# tests pin down that the schema block actually expands them.
def test_schema_prompt_block_lists_enum_values_not_a_bare_any():
    block = schema_prompt_block(WithEnumAndScope)
    assert "supports" in block and "refutes" in block
    assert ": any" not in block


def test_schema_prompt_block_expands_nested_object_fields():
    block = schema_prompt_block(WithEnumAndScope)
    assert "geo" in block and "segment" in block


async def test_field_split_asks_for_enum_values_and_nested_fields_not_a_bare_any():
    """If the field-split downgrade can't tell the model that `direction`
    must be one of two enum values, or that `scope` is an object with geo and
    segment keys, the downgrade guarantees failure on exactly the fields it
    exists to rescue."""
    client = Scripted('{"bad":1}', '{"bad":2}', "supports", '{"geo":"IN","segment":"smb"}')
    rep = await structured_report(client, role="fast", prompt="go", schema=WithEnumAndScope)
    split_prompts = client.prompts[2:]
    assert "supports" in split_prompts[0] or "refutes" in split_prompts[0]
    assert rep.stages == ["initial", "repair", "field_split"]
    assert rep.value == WithEnumAndScope(
        direction=Direction.SUPPORTS, scope=Scope(geo="IN", segment="smb"))


# ── extra: _extract_json must not merge two distinct JSON objects ──────────
async def test_a_response_with_two_json_objects_yields_only_the_first():
    """A greedy 'first { to last }' match would splice both objects into one
    invalid blob. The first complete, balanced object should be recovered on
    its own instead."""
    client = Scripted('Here: {"name":"a","count":1} and also {"name":"b","count":2}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=1)
    assert rep.stages == ["initial"]


# ── structured() and structured_many() convenience wrappers ────────────────
async def test_structured_returns_just_the_value():
    client = Scripted('{"name":"a","count":2}')
    from jury.llm.structured import structured
    value = await structured(client, role="fast", prompt="go", schema=Tiny)
    assert value == Tiny(name="a", count=2)


async def test_structured_many_drops_failures_and_keeps_successes():
    client = Scripted(
        '{"name":"a","count":1}',            # prompt 1: succeeds immediately
        '{"bad":1}', '{"bad":2}', "x", "y",   # prompt 2: fails all the way to dropped
        '{"name":"c","count":3}',             # prompt 3: succeeds immediately
    )
    values = await structured_many(client, role="fast",
                                   prompts=["p1", "p2", "p3"], schema=Tiny)
    assert values == [Tiny(name="a", count=1), Tiny(name="c", count=3)]
