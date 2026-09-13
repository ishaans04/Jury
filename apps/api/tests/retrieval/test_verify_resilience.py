"""Fix round 1 (code review): verify_claim is the integrity gate -- the one
place a claim is allowed to die, but the run is not. It must never propagate
an exception raised by the `FetchClient` it was handed, and must never trust
that the client's `text` field is a `str`.
"""
from jury.retrieval.verify import Rejection, verify_claim
from jury.schemas.claim import ClaimRecord
from jury.transport.protocols import FetchResult

MAP = {"x.test": 3}


def claim(**kw) -> ClaimRecord:
    base = {"assumption_id": "a1", "direction": "supports", "variable": "price_monthly",
            "value_num": 149.0, "unit": "INR_per_month",
            "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.8,
            "source_url": "https://x.test/pricing", "source_tier": 1,
            "excerpt": "Starter plan is priced at 149 INR per month", "chair": "market"}
    return ClaimRecord.model_validate(base | kw)


class RaisingFetch:
    async def fetch(self, url):
        raise RuntimeError("transport exploded")


class NoneTextFetch:
    async def fetch(self, url):
        return FetchResult(url=url, status=200, text=None)


async def test_a_fetch_client_that_raises_yields_a_rejection_not_a_crash():
    out = await verify_claim(claim(), RaisingFetch(), domain_map=MAP)
    assert isinstance(out, Rejection)
    assert "RuntimeError" in out.reason


async def test_a_non_str_text_body_yields_a_rejection_not_a_crash():
    out = await verify_claim(claim(), NoneTextFetch(), domain_map=MAP)
    assert isinstance(out, Rejection)
    assert "excerpt" in out.reason.lower() or "text" in out.reason.lower()
