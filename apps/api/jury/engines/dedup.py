"""Deduplication. P10: the same source found twice never raises confidence.

PRD §12.1: dedup_hash = sha256(canonical_url || variable || scope_geo
                               || scope_segment || scope_tier)
"""
import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jury.schemas.scope import Scope

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset({
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer",
    "igshid", "si", "spm", "_hsenc", "_hsmi", "yclid", "twclid",
})
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def canonicalise_url(url: str) -> str:
    """Strip tracking parameters, fragments and trailing slashes before hashing.

    PRD §16.1: "Canonicalisation strips tracking parameters, fragments, and
    trailing slashes before hashing."
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()

    host = parts.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if parts.port and str(parts.port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"

    path = parts.path.rstrip("/")

    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_KEYS
        and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(kept))

    return urlunsplit((scheme, netloc, path, query, ""))


def dedup_hash(canonical_url: str, variable: str | None, scope: Scope) -> str:
    """Five components exactly, per PRD §12.1. Period is deliberately excluded."""
    payload = "\x1f".join([
        canonical_url,
        variable or "",
        scope.geo.value,
        scope.segment.value,
        scope.tier.value if scope.tier else "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
