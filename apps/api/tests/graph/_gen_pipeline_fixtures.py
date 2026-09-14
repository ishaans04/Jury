"""One-off generator for the archetype-detection and assumption-extraction
fixtures the graph tests need for GRAPH_PITCH (tests/graph/test_graph.py).
Not collected as a test (leading underscore). Run with
`uv run python tests/graph/_gen_pipeline_fixtures.py`.
"""
import json

from jury.llm.prompts import archetype_detection_prompt, assumption_extraction_prompt
from jury.llm.structured import schema_prompt_block
from jury.graph.nodes.archetype import ArchetypeResult
from jury.graph.nodes.extract import ExtractionResult
from jury.transport.fixtures import FIXTURE_ROOT, request_key

GRAPH_PITCH = "GraphCo pipeline test pitch for invoicing software for small businesses"

CLASSES: list[tuple[str, float, str]] = [
    ("saas.pain_severity", 1.0, "Is the pain acute enough to pay for?"),
    ("saas.wtp_above_cost", 1.0, "Does willingness to pay exceed delivered cost per account?"),
    ("saas.retention", 1.0, "Will accounts stay long enough to repay acquisition?"),
    ("saas.channel_cost", 1.0, "Is CAC recoverable within an acceptable payback?"),
    ("saas.buyer_identity", 0.6, "Is there a budget holder who can actually buy?"),
    ("saas.switching_cost", 0.6, "What makes them leave the current solution?"),
    ("saas.dependency_risk", 0.6, "Do required third parties permit this at viable cost?"),
    ("saas.data_compliance", 0.6, "Any data, privacy or regulatory constraint?"),
    ("saas.incumbency", 0.3, "Is the category already won or already a graveyard?"),
    ("saas.expansion", 0.3, "Is there an observable adjacency for expansion?"),
]


def _save(kind: str, key: str, payload: dict) -> None:
    path = FIXTURE_ROOT / kind / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _record(role: str, prompt: str, schema, value: dict) -> None:
    block = schema_prompt_block(schema)
    messages = [{"role": "user", "content": f"{prompt}\n\n{block}"}]
    key = request_key(role, json.dumps(messages, sort_keys=True))
    _save("llm", key, {"text": json.dumps(value)})


_record(
    "fast", archetype_detection_prompt(GRAPH_PITCH), ArchetypeResult,
    {"archetype": "subscription_saas", "confidence": 0.9,
     "inferred_scope": {"geo": "IN", "segment": "smb", "tier": None, "period": None},
     "reasoning": "GraphCo pitch fixture for the Task 4.3 graph integration test."})

_record(
    "reasoning", assumption_extraction_prompt(GRAPH_PITCH, CLASSES), ExtractionResult,
    {"assumptions": [
        {"statement": "SMB owners find manual GST filing painful enough to pay for automation.",
         "class_key": "saas.pain_severity", "origin": "founder", "discovered_by": None,
         "criticality": "blocking", "uncertainty": "uncertain", "falsifiability": "testable_now",
         "asserted_variable": None, "asserted_value": None, "asserted_unit": None},
        {"statement": "Customers keep paying month over month rather than churning quickly.",
         "class_key": "saas.retention", "origin": "founder", "discovered_by": None,
         "criticality": "high", "uncertainty": "unknown", "falsifiability": "testable_costly",
         "asserted_variable": None, "asserted_value": None, "asserted_unit": None},
        {"statement": "Customer acquisition cost stays recoverable within an acceptable payback.",
         "class_key": "saas.channel_cost", "origin": "founder", "discovered_by": None,
         "criticality": "medium", "uncertainty": "uncertain", "falsifiability": "testable_now",
         "asserted_variable": None, "asserted_value": None, "asserted_unit": None},
    ]})

print("pipeline fixtures written")
