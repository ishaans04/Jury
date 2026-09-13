"""Structured-output enforcement. PRD §15.3 -- all five mitigations, mandatory.

Open-weight models are weaker at strict structured output than frontier models.
Since every chair's output contract is a typed JSON record (PRD §6.1), this is
the single largest reliability risk in the build. This module is the mitigation.

Escalation, in order and never skipped:
    initial -> repair -> field_split -> dropped
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from jury.tracing.events import TraceSink
from jury.transport.protocols import LLMClient, LLMResponse

RepairStage = Literal["initial", "repair", "field_split", "dropped"]

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(slots=True)
class RepairReport:
    value: BaseModel | None
    stages: list[RepairStage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── schema rendering ─────────────────────────────────────────────────────────
#
# A pydantic v2 JSON schema represents an enum field or a nested-object field
# as `{"$ref": "#/$defs/Name"}` (or, if the field is optional, as an `anyOf`
# with that same `$ref` alongside `{"type": "null"}`) -- there is no "type"
# key on the property itself. ClaimRecord (PRD §6.1, the real schema this
# module exists to serve) has exactly this shape on `direction`, `chair`,
# `scope`, and `new_assumption`: four of its thirteen fields. A renderer that
# only reads `spec.get("type")` therefore collapses every one of them to a
# bare "any" -- silently discarding the enum's allowed values and the nested
# object's required keys on exactly the fields where an explicit list matters
# most (PRD §15.3 mitigation 2 exists because prose descriptions do not work;
# "any" is even less than prose). The resolution below walks `$ref`/`anyOf`
# against `$defs` so enums and nested objects render their real shape.


def _resolve_ref(spec: dict, defs: dict) -> dict:
    if "$ref" in spec:
        key = spec["$ref"].rsplit("/", 1)[-1]
        return defs.get(key, spec)
    return spec


def _unwrap(spec: dict, defs: dict) -> tuple[dict, bool]:
    """Resolve a possibly-nullable, possibly-$ref'd property spec.

    Returns (resolved_spec, nullable).
    """
    if "anyOf" in spec:
        members = spec["anyOf"]
        non_null = [m for m in members if m.get("type") != "null"]
        nullable = len(non_null) < len(members)
        target = non_null[0] if non_null else members[0]
        return _resolve_ref(target, defs), nullable
    return _resolve_ref(spec, defs), False


def _describe(name: str, spec: dict, defs: dict, required: set[str]) -> tuple[str, dict | None]:
    """One rendered line for a field, plus its nested object schema if any."""
    resolved, nullable = _unwrap(spec, defs)
    flag = "required" if name in required else "optional"
    if nullable:
        flag += ", nullable"

    if "enum" in resolved:
        return f'  "{name}": string, one of {resolved["enum"]} ({flag})', None

    if resolved.get("type") == "object" and "properties" in resolved:
        return f'  "{name}": object, see its own fields below ({flag})', resolved

    kind = resolved.get("type", "any")
    bound = ""
    if "minimum" in resolved:
        bound += f", minimum {resolved['minimum']}"
    if "maximum" in resolved:
        bound += f", maximum {resolved['maximum']}"
    return f'  "{name}": {kind} ({flag}{bound})', None


def schema_prompt_block(schema: type[BaseModel]) -> str:
    """Render the schema for embedding in the prompt (mitigation 2).

    Small models follow an explicit field list far better than a prose
    description of the same thing -- and, for an enum or nested-object field,
    far better than a bare "any" that hides the allowed values or required
    sub-keys entirely.
    """
    js = schema.model_json_schema()
    defs = js.get("$defs", {})
    required = set(js.get("required", []))
    lines = ["Return ONE JSON object with exactly these keys:"]
    nested_blocks: list[str] = []
    for name, spec in js.get("properties", {}).items():
        line, nested = _describe(name, spec, defs, required)
        lines.append(line)
        if nested is not None:
            nested_required = set(nested.get("required", []))
            nested_lines = [f'  fields of "{name}":']
            for nname, nspec in nested.get("properties", {}).items():
                nline, _ = _describe(nname, nspec, defs, nested_required)
                nested_lines.append("  " + nline)
            nested_blocks.append("\n".join(nested_lines))
    lines.extend(nested_blocks)
    lines.append("No prose. No markdown fences. No trailing commentary.")
    return "\n".join(lines)


# ── recovering JSON from a chatty small model ───────────────────────────────


def _balanced_objects(text: str) -> list[tuple[int, str]]:
    """Return (start_offset, span) for every top-level syntactically-balanced
    {...} span in text, in the order they appear.

    A regex that matches from the first "{" to the very last "}" merges two
    separate JSON objects into one invalid blob and mishandles an incidental
    brace in surrounding prose. Retrying every '{' as an independent start
    recovers each complete top-level object instead. String literals are
    tracked so a literal brace inside a quoted value doesn't confuse the
    depth count, and once a span balances, the scan resumes after it rather
    than also matching the objects nested inside it. The start offset is
    returned alongside each span so `_json_candidates` can merge these with
    the candidates found inside fenced blocks and sort the combined set by
    where each one actually sits in the original response.
    """
    spans: list[tuple[int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        end = None
        for j in range(i, n):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
        if end is not None:
            spans.append((i, text[i : end + 1]))
            i = end + 1
        else:
            # this '{' never closes; the next '{' (if any) might still be
            # the start of a real, balanced object further along.
            i += 1
    return spans


def _json_candidates(text: str) -> list[str]:
    """Every plausible JSON-object candidate anywhere in the response --
    inside every fenced block AND in the loose text around them -- in the
    order they appear in the original response.

    A model that has been shown the schema (mitigation 2 puts it in every
    prompt) will often fence its illustrative example, since fencing is
    exactly what a schema-aware assistant tends to do with a "for example"
    JSON blob. An earlier version special-cased fencing: `_FENCE.search`
    (first match only) and, whenever any fence existed, scanned *only*
    inside it, discarding every loose candidate outside. That reintroduced
    Finding 1's exact bug through a path last-preference never touched --
    fenced-vs-fenced and fenced-vs-loose ordering was never considered at
    all, so a fenced EXAMPLE still beat a later, correct real answer purely
    because it was fenced and checked first, regardless of which one
    actually came last in the response. Fencing is no longer given priority
    over position: every fenced block's content is scanned for balanced
    objects, every span of loose text outside any fence is scanned the same
    way, and all candidates are merged and sorted by their position in the
    original text before `_parse` applies last-preference across the whole
    set -- a fence signals "this might be JSON", not "this is the final
    answer".

    Falls back to the last fence's content (if any fence exists) or the raw
    text when no balanced object is found anywhere, which keeps today's
    behaviour for a scalar or genuinely unparseable answer.
    """
    fence_matches = list(_FENCE.finditer(text))
    candidates: list[tuple[int, str]] = []

    for m in fence_matches:
        inner_start = m.start(1)
        for start_off, span in _balanced_objects(m.group(1)):
            candidates.append((inner_start + start_off, span))

    if fence_matches:
        masked = list(text)
        for m in fence_matches:
            for k in range(m.start(), m.end()):
                masked[k] = " "
        loose_text = "".join(masked)
    else:
        loose_text = text

    for start_off, span in _balanced_objects(loose_text):
        candidates.append((start_off, span))

    candidates.sort(key=lambda item: item[0])
    if candidates:
        return [span for _, span in candidates]

    if fence_matches:
        return [fence_matches[-1].group(1).strip()]
    return [text.strip()]


def _extract_json(text: str) -> str:
    """Best-effort single JSON snippet for the field-split scalar coercion
    (`_coerce_scalar`), which only ever expects one answer per call. Prefers
    the *last* candidate for the same reason `_parse` does below: the schema
    is embedded in every prompt, so an earlier candidate is more likely to
    be an echoed example than the model's actual answer."""
    return _json_candidates(text)[-1]


def _parse(text: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    """Validate every candidate object in `text`, preferring the *last* one
    that validates.

    Taking the first candidate that validates is not safe: the schema is
    embedded in every prompt (mitigation 2), so a model that echoes a
    schema-shaped example before its real answer produces an earlier
    candidate that is often schema-valid too (it's shaped by the same
    schema) while being the wrong data. Walking from the end picks the
    model's actual answer over its own worked example in the common case,
    where the real answer follows any preamble. If nothing validates, the
    error reported is the *last* candidate's -- it is far more likely to be
    the model's real (failed) attempt than a preamble example, so the repair
    prompt shows the model what it actually got wrong.

    This is a heuristic on source position, not a guarantee, and it has a
    known failure mode: given
    'Here is my answer {"name":"a","count":2} -- for instance another one
    would be {"name":"decoy","count":9}', both candidates validate and this
    picks the decoy, because it comes last. That trade is taken deliberately
    -- for this model class, a chatty *preamble* before the real answer
    (an echoed schema example, a worked-through explanation) is far more
    common than a chatty *postamble* that itself contains a second,
    independently valid JSON object, so preferring the last valid candidate
    wins on expected value even though it is not sound in general. If a
    later phase observes wrong-object selection in real traces, the fix is
    to stop deciding by position and instead score each valid candidate by
    how much of the prompt's own context it accounts for -- e.g. required-
    field coverage, or overlap with values mentioned earlier in the prompt --
    rather than by where in the response it happens to sit.
    """
    candidates = _json_candidates(text)
    last_candidate_error: str | None = None
    for candidate in reversed(candidates):
        try:
            return schema.model_validate_json(candidate), None
        except (ValidationError, ValueError) as err:
            if last_candidate_error is None:
                last_candidate_error = str(err)
    return None, last_candidate_error


def _coerce_scalar(text: str) -> object:
    """A single-field answer may arrive quoted, fenced, bare, or as a small
    JSON object/array (for a nested-object field asked for on its own)."""
    raw = _extract_json(text).strip().strip("`").strip()
    if raw.lower() in ("null", "none", ""):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.strip('"').strip()


# ── the escalation itself ───────────────────────────────────────────────────


async def structured_report(
    client: LLMClient, *, role: str, prompt: str, schema: type[BaseModel],
    trace: TraceSink | None = None,
) -> RepairReport:
    """Produce a validated instance of `schema`, or None having tried everything.

    When `trace` is given, one `llm_call` row is emitted per attempt (stage
    name, model role, token counts, latency) and, if the claim is ultimately
    dropped, a final `error` row carrying every accumulated reason -- without
    this, a dropped claim shows up in run_events as a node that ran and
    produced nothing, with no way to see which stage failed or why (PRD
    §11.2 dec. 9). `trace` is None by default and every call site below is a
    no-op in that case, so omitting it behaves exactly as before.
    """
    report = RepairReport(value=None)
    block = schema_prompt_block(schema)

    async def _call(stage: RepairStage, content: str, *, json_mode: bool,
                    field_name: str | None = None) -> LLMResponse:
        started = time.perf_counter()
        response = await client.complete(
            model=role, messages=[{"role": "user", "content": content}],
            json_mode=json_mode)
        if trace is not None:
            detail = {"stage": stage, "role": role, "model": response.model,
                      "prompt_tokens": response.prompt_tokens,
                      "completion_tokens": response.completion_tokens}
            if field_name is not None:
                detail["field"] = field_name
            await trace.emit(node="structured", event="llm_call", detail=detail,
                             latency_ms=int((time.perf_counter() - started) * 1000))
        return response

    # ── stage 1: initial, JSON mode on, schema embedded ─────────────────────
    report.stages.append("initial")
    first = await _call("initial", f"{prompt}\n\n{block}", json_mode=True)
    value, error = _parse(first.text, schema)
    if value is not None:
        report.value = value
        return report
    report.errors.append(error or "unparseable")

    # ── stage 2: repair -- error and offending output attached ──────────────
    report.stages.append("repair")
    repair_prompt = (
        f"{prompt}\n\n{block}\n\n"
        f"Your previous answer was rejected by schema validation.\n"
        f"Previous answer:\n{first.text}\n\n"
        f"Validation error:\n{error}\n\n"
        f"Return corrected JSON only.")
    second = await _call("repair", repair_prompt, json_mode=True)
    value, error2 = _parse(second.text, schema)
    if value is not None:
        report.value = value
        return report
    report.errors.append(error2 or "unparseable")

    # ── stage 3: field-split downgrade ──────────────────────────────────────
    report.stages.append("field_split")
    js = schema.model_json_schema()
    defs = js.get("$defs", {})
    assembled: dict[str, object] = {}
    for name, spec in js.get("properties", {}).items():
        resolved, nullable = _unwrap(spec, defs)
        if "enum" in resolved:
            hint = f"one of {resolved['enum']}"
        elif resolved.get("type") == "object" and "properties" in resolved:
            nested_required = set(resolved.get("required", []))
            field_lines = [
                _describe(nname, nspec, defs, nested_required)[0].strip()
                for nname, nspec in resolved.get("properties", {}).items()
            ]
            hint = "a JSON object with these keys:\n" + "\n".join(field_lines)
        else:
            hint = resolved.get("type", "any")
        if nullable:
            hint += " (or null if not applicable)"

        ask = (f"{prompt}\n\n"
               f'Answer with ONLY the value for the single field "{name}" '
               f"({hint}). No other keys. No prose -- just the value.")
        one = await _call("field_split", ask, json_mode=False, field_name=name)
        assembled[name] = _coerce_scalar(one.text)

    try:
        report.value = schema.model_validate(assembled)
        return report
    except ValidationError as err:
        report.errors.append(str(err))

    # ── stage 4: drop the claim ─────────────────────────────────────────────
    # A dropped claim is acceptable; a malformed ledger row is not (PRD §15.3).
    report.stages.append("dropped")
    report.value = None
    if trace is not None:
        await trace.emit(node="structured", event="error",
                         detail={"reasons": list(report.errors)})
    return report


async def structured(client: LLMClient, *, role: str, prompt: str,
                     schema: type[BaseModel],
                     trace: TraceSink | None = None) -> BaseModel | None:
    """Convenience wrapper when the caller does not need the escalation trace."""
    return (await structured_report(client, role=role, prompt=prompt,
                                    schema=schema, trace=trace)).value


async def structured_many(client: LLMClient, *, role: str, prompts: list[str],
                          schema: type[BaseModel]) -> list[BaseModel]:
    """Run `structured` over several prompts, dropping any that fail every
    escalation stage. A dropped claim vanishes from the list rather than
    appearing as a gap the caller must special-case (PRD §15.3 mitigation 5)."""
    out: list[BaseModel] = []
    for one_prompt in prompts:
        value = await structured(client, role=role, prompt=one_prompt, schema=schema)
        if value is not None:
            out.append(value)
    return out
