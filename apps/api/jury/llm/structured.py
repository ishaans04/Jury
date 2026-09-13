"""Structured-output enforcement. PRD §15.3 -- all five mitigations, mandatory.

Open-weight models are weaker at strict structured output than frontier models.
Since every chair's output contract is a typed JSON record (PRD §6.1), this is
the single largest reliability risk in the build. This module is the mitigation.

Escalation, in order and never skipped:
    initial -> repair -> field_split -> dropped
"""
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from jury.transport.protocols import LLMClient

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


def _first_balanced_object(text: str) -> str | None:
    """Return the first syntactically-balanced {...} span in text.

    A regex that matches from the first "{" to the very last "}" merges two
    separate JSON objects in the same response into one invalid blob, and
    mishandles an incidental brace in surrounding prose. Scanning for the
    first span whose braces actually balance (respecting string literals so a
    literal brace inside a quoted value doesn't confuse the count) recovers
    just the first complete object instead.
    """
    n = len(text)
    for start in range(n):
        if text[start] != "{":
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, n):
            c = text[i]
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
                        return text[start : i + 1]
        # this '{' never closes; the next '{' (if any) might still be the
        # start of a real, balanced object further along.
    return None


def _extract_json(text: str) -> str:
    """Small models wrap JSON in fences and chatter. Recover the object."""
    fenced = _FENCE.search(text)
    scan = fenced.group(1) if fenced else text
    obj = _first_balanced_object(scan)
    return obj if obj is not None else scan.strip()


def _parse(text: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    try:
        return schema.model_validate_json(_extract_json(text)), None
    except (ValidationError, ValueError) as err:
        return None, str(err)


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
) -> RepairReport:
    """Produce a validated instance of `schema`, or None having tried everything."""
    report = RepairReport(value=None)
    block = schema_prompt_block(schema)

    # ── stage 1: initial, JSON mode on, schema embedded ─────────────────────
    report.stages.append("initial")
    first = await client.complete(
        model=role, messages=[{"role": "user", "content": f"{prompt}\n\n{block}"}],
        json_mode=True)
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
    second = await client.complete(
        model=role, messages=[{"role": "user", "content": repair_prompt}],
        json_mode=True)
    value, error2 = _parse(second.text, schema)
    if value is not None:
        report.value = value
        return report
    report.errors.append(error2 or "unparseable")

    # ── stage 3: field-split downgrade ──────────────────────────────────────
    report.stages.append("field_split")
    js = schema.model_json_schema()
    defs = js.get("$defs", {})
    required = set(js.get("required", []))
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
        one = await client.complete(model=role,
                                    messages=[{"role": "user", "content": ask}],
                                    json_mode=False)
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
    return report


async def structured(client: LLMClient, *, role: str, prompt: str,
                     schema: type[BaseModel]) -> BaseModel | None:
    """Convenience wrapper when the caller does not need the escalation trace."""
    return (await structured_report(client, role=role, prompt=prompt,
                                    schema=schema)).value


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
