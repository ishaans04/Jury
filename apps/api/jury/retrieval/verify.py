"""Pre-persist verification. P1 and PRD §18.

"This check is the product's integrity guarantee and is non-optional."

Two conditions, both required before a claim may become a ledger row:
  1. the source URL was actually fetched and returned 2xx
  2. the excerpt is present in the extracted text

Tier is then reassigned by rule (PRD §16.2), overriding whatever the model said.
"""
import re
import unicodedata
from dataclasses import dataclass

from jury.engines.dedup import canonicalise_url
from jury.retrieval.ssrf import is_fetch_allowed
from jury.retrieval.tiers import assign_tier
from jury.schemas.claim import ClaimRecord
from jury.transport.protocols import FetchClient

_WS = re.compile(r"\s+")
_PUNCT_FOLD = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}


@dataclass(frozen=True, slots=True)
class VerifiedClaim:
    claim: ClaimRecord
    tier: int
    canonical_url: str
    extracted_text: str
    http_status: int


@dataclass(frozen=True, slots=True)
class Rejection:
    claim: ClaimRecord
    reason: str


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for bad, good in _PUNCT_FOLD.items():
        text = text.replace(bad, good)
    return _WS.sub(" ", text).strip().lower()


def excerpt_is_present(excerpt: str, text: str) -> bool:
    """Verbatim substring match after whitespace, case and punctuation folding.

    Deliberately NOT fuzzy: PRD §6.1 specifies "verbatim supporting text", and a
    similarity threshold is exactly the loophole a hallucinated statistic slips
    through.
    """
    needle = _normalise(excerpt)
    if not needle:
        return False
    return needle in _normalise(text)


async def verify_claim(claim: ClaimRecord, fetch: FetchClient, *,
                       domain_map: dict[str, int]) -> VerifiedClaim | Rejection:
    allowed, reason = is_fetch_allowed(claim.source_url)
    if not allowed:
        return Rejection(claim, f"blocked url: {reason}")

    # This is the integrity gate: nothing downstream may crash the run because
    # a transport it does not control (a live client, a cache backend behind
    # it, a fixture with a bad recording) misbehaved. A dropped claim is
    # correct behaviour here (PRD §18: degrade to less evidence); a crashed
    # chair is not. Any exception from the fetch call itself -- not just a
    # non-2xx response -- becomes a Rejection.
    try:
        result = await fetch.fetch(claim.source_url)
    except Exception as exc:  # noqa: BLE001 - deliberately blanket, see above
        return Rejection(claim, f"fetch raised {type(exc).__name__}: {exc}")

    if not (200 <= result.status < 300):
        return Rejection(claim, f"source returned http {result.status}")
    text = result.text if isinstance(result.text, str) else ""
    if not text.strip():
        return Rejection(claim, "source returned no extractable text")
    if not excerpt_is_present(claim.excerpt, text):
        return Rejection(claim, "excerpt absent from the extracted text")

    tier = assign_tier(claim.source_url, domain_map)
    if tier is None:
        return Rejection(claim, "source url unresolvable for tier assignment")

    return VerifiedClaim(claim=claim, tier=tier,
                         canonical_url=canonicalise_url(claim.source_url),
                         extracted_text=text, http_status=result.status)
