"""One-off generator for tests/graph/test_graph.py's chair fixtures.

Not a test itself (leading underscore keeps pytest from collecting it). Run
manually with `uv run python tests/graph/_gen_fixtures.py` whenever the fixed
pitch/domains below change. Writes into the shared tests/fixtures/ tree the
same way every other chair test's fixtures were recorded, except these
claims all use `new_assumption` rather than a fixed `assumption_id` --
deliberately, so the graph-level integration test does not need the fan-out's
newly-created (fresh-uuid) assumption rows to match a pre-baked literal id.
"""
import json
from types import SimpleNamespace

from jury.chairs import customer, dependencies, economics, market, precedent
from jury.llm.structured import schema_prompt_block
from jury.schemas.claim import ClaimRecord
from jury.transport.fixtures import FIXTURE_ROOT, request_key

PITCH = "GraphCo pipeline test pitch for invoicing software for small businesses"
CTX = SimpleNamespace(pitch=PITCH, target_scope=SimpleNamespace(
    geo=SimpleNamespace(value="IN"), segment=SimpleNamespace(value="smb")))

BLOCK = schema_prompt_block(ClaimRecord)


def _hit(url: str, title: str):
    return SimpleNamespace(url=url, title=title, snippet="")


def _save(kind: str, key: str, payload: dict) -> None:
    path = FIXTURE_ROOT / kind / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _llm_key(role: str, content: str) -> str:
    messages = [{"role": "user", "content": content}]
    prompt = json.dumps(messages, sort_keys=True)
    return request_key(role, prompt)


def record(build_prompt_fn, role: str, provider: str, query: str, url: str, title: str,
          page_text: str, claim: dict) -> None:
    _save("search", request_key(provider, query), {"hits": [
        {"url": url, "title": title, "snippet": ""}]})
    _save("fetch", request_key(url), {"status": 200, "text": page_text,
                                      "content_type": "text/html"})
    content = f"{build_prompt_fn(CTX, _hit(url, title), page_text)}\n\n{BLOCK}"
    _save("llm", _llm_key(role, content), {"text": json.dumps(claim)})


record(
    market._build_prompt, market._LLM_ROLE, "brave", f"{PITCH} pricing",
    url="https://graphco-market.test/pricing", title="GraphCo pricing",
    page_text="GraphCo competitor pricing is 299 INR per month for the standard plan.",
    claim={
        "assumption_id": None,
        "new_assumption": {"statement": "A market-rate competitor charges 299 INR/month",
                           "class_key": "saas.wtp_above_cost"},
        "direction": "refutes", "variable": "price_monthly", "value_num": 299.0,
        "value_min": None, "value_max": None, "unit": "INR_per_month",
        "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.7,
        "source_url": "https://graphco-market.test/pricing", "source_tier": 1,
        "excerpt": "GraphCo competitor pricing is 299 INR per month for the standard plan.",
        "chair": "market",
    })

record(
    customer._build_prompt, customer._LLM_ROLE, "hn", f"{PITCH} complaints",
    url="https://graphco-customer.test/thread", title="GraphCo customer thread",
    page_text="I cancelled GraphCo because the free trial felt too short for a small shop.",
    claim={
        "assumption_id": None,
        "new_assumption": {"statement": "Customers cancel after a short free trial",
                           "class_key": "saas.retention"},
        "direction": "refutes", "variable": None, "value_num": None, "value_min": None,
        "value_max": None, "unit": None, "scope": {"geo": "IN", "segment": "smb"},
        "confidence": 0.6, "source_url": "https://graphco-customer.test/thread",
        "source_tier": 4,
        "excerpt": "I cancelled GraphCo because the free trial felt too short for a small shop.",
        "chair": "customer",
    })

record(
    precedent._build_outcome_prompt, precedent._LLM_ROLE, "brave", f"{PITCH} similar company shut down",
    url="https://graphco-precedent.test/news", title="GraphCo precedent news",
    page_text="A similar invoicing startup called LedgerCo shut down in 2021 after two years.",
    claim={
        "assumption_id": None,
        "new_assumption": {"statement": "A similar invoicing startup shut down in 2021",
                           "class_key": "saas.incumbency"},
        "direction": "refutes", "variable": None, "value_num": None, "value_min": None,
        "value_max": None, "unit": None, "scope": {"geo": "IN", "segment": "smb"},
        "confidence": 0.65, "source_url": "https://graphco-precedent.test/news",
        "source_tier": 2,
        "excerpt": "A similar invoicing startup called LedgerCo shut down in 2021 after two years.",
        "chair": "precedent",
    })

record(
    dependencies._build_prompt, dependencies._LLM_ROLE, "brave", f"{PITCH} API pricing per call",
    url="https://graphco-deps.test/docs", title="GraphCo payment docs",
    page_text="Standard pricing is 2.9 percent plus 30 cents per charge for the payments API.",
    claim={
        "assumption_id": None,
        "new_assumption": {"statement": "The payments API charges 2.9 percent plus 30 cents",
                           "class_key": "saas.dependency_risk"},
        "direction": "refutes", "variable": "payments_api_price", "value_num": 2.9,
        "value_min": None, "value_max": None, "unit": "percent_plus_30_cents",
        "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.6,
        "source_url": "https://graphco-deps.test/docs", "source_tier": 1,
        "excerpt": "Standard pricing is 2.9 percent plus 30 cents per charge for the payments API.",
        "chair": "dependencies",
    })

record(
    economics._build_prompt, economics._LLM_ROLE, "brave", f"{PITCH} industry average CAC benchmark",
    url="https://graphco-econ.test/benchmarks", title="GraphCo benchmarks",
    page_text="Industry average CAC for SMB invoicing SaaS is 400 INR per acquired account.",
    claim={
        "assumption_id": None,
        "new_assumption": {"statement": "Industry average CAC is 400 INR per account",
                           "class_key": "saas.channel_cost"},
        "direction": "supports", "variable": "cac", "value_num": 400.0, "value_min": None,
        "value_max": None, "unit": "INR", "scope": {"geo": "IN", "segment": "smb"},
        "confidence": 0.6, "source_url": "https://graphco-econ.test/benchmarks",
        "source_tier": 2,
        "excerpt": "Industry average CAC for SMB invoicing SaaS is 400 INR per acquired account.",
        "chair": "economics",
    })

print("fixtures written")
