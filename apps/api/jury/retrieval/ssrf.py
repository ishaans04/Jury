"""SSRF guard. PRD §17.4.

Target URLs are partly model-selected, so this is a real attack surface rather
than a theoretical one. Blocking happens before any socket is opened.

DNS is deliberately NOT resolved here. This guard only rejects requests whose
*literal* host -- after canonicalising trailing dots, case, and encoded-IP
forms -- is already a loopback/private/link-local/metadata address, plus a
couple of string-level checks (scheme, credentials, non-ASCII hostnames). A
perfectly ordinary public hostname that *resolves* to a private address (DNS
rebinding, or just an attacker-controlled DNS record) passes this guard
untouched -- that is a transport-layer problem, not a URL-string problem.
Whoever implements the fetch layer (jury/transport/fetch.py, which does not
exist yet) MUST pin the outbound connection to the IP address actually
returned by DNS and re-validate *that* address before connecting, rather
than trusting the hostname a second time. Without that, this guard's
protection stops at the literal-encoding bypasses it was built for.
"""
import ipaddress
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset({
    "localhost", "metadata.google.internal", "metadata",
    "instance-data", "169.254.169.254",
})


class BlockedURL(Exception):
    """Raised when an outbound fetch target fails the guard."""


def _parse_int_component(part: str) -> int | None:
    """Parse one dot-separated component using classic BSD inet_aton rules:
    a `0x`/`0X` prefix means hex, a lone leading `0` (length > 1) means octal,
    otherwise decimal. This is deliberately more permissive than
    `ipaddress`, because it is the *attacker's* parser we need to match, not
    the standard library's strict one.
    """
    if not part:
        return None
    lowered = part.lower()
    try:
        if lowered.startswith("0x"):
            return int(part, 16)
        if len(part) > 1 and part[0] == "0":
            return int(part, 8)
        return int(part, 10)
    except ValueError:
        return None


def _parse_legacy_ipv4(candidate: str) -> ipaddress.IPv4Address | None:
    """Mimic inet_aton's tolerant IPv4 literal grammar.

    `ipaddress.ip_address` only accepts strict 4-part decimal dotted-quads
    (or a handful of other RFC-conformant forms). It rejects a bare integer
    (`2130706433`), a bare hex integer (`0x7f000001`), octal-per-octet
    (`0177.0.0.1`), hex-per-octet (`0x7f.0.0.1`), and shorthand forms with
    fewer than four octets (`127.1`) — every one of which curl, glibc's
    `inet_aton`, and plenty of production HTTP stacks still resolve to a
    concrete address. Those are the standard loopback-encoding bypasses, so
    this guard has to parse them the same tolerant way an attacker would.
    """
    parts = candidate.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    nums = [_parse_int_component(p) for p in parts]
    if any(n is None or n < 0 for n in nums):
        return None
    # Every component but the last must fit in a single byte; the last one
    # absorbs whatever bits remain (inet_aton's "shorthand" behaviour).
    if any(n > 0xFF for n in nums[:-1]):
        return None
    last_bits = 32 - 8 * (len(nums) - 1)
    if nums[-1] > (1 << last_bits) - 1:
        return None
    value = 0
    for n in nums[:-1]:
        value = (value << 8) | n
    value = (value << last_bits) | nums[-1]
    return ipaddress.IPv4Address(value)


def _host_as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Resolve literal forms only: dotted quad, IPv6 (incl. `::ffff:`-mapped
    IPv4, which `ipaddress` already classifies as loopback/link-local
    correctly), and the tolerant/encoded IPv4 forms above.

    DNS is deliberately not resolved here — a hostname that resolves to a
    private address is caught by the transport's own no-redirect-to-private
    policy in fetch.py. What this catches is the literal-encoding bypass.
    """
    candidate = host.strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    return _parse_legacy_ipv4(candidate)


def is_fetch_allowed(url: str) -> tuple[bool, str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "unparseable url"

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"scheme {parts.scheme!r} not permitted"
    if parts.username or parts.password:
        return False, "credentials in url"

    # Canonicalise once, here, so every check below (blocklist and IP parser
    # alike) sees the same form a resolver would. A trailing dot marks a DNS
    # name as already fully-qualified -- resolvers treat "localhost." exactly
    # like "localhost" -- and rstrip(".") collapses any number of them, so
    # "localhost.." is caught too without needing its own case.
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return False, "missing host"
    # Non-ASCII hosts are rejected outright rather than normalised: some IDNA
    # tables (the stdlib's IDNA2003/Nameprep codec, notably) fold certain
    # Unicode compatibility characters -- e.g. fullwidth Latin letters -- down
    # to plain ASCII, so a Unicode string that is not literally "localhost"
    # can still IDNA-encode to it at connect time. Refusing non-ASCII hosts
    # here closes that whole class without this guard having to reimplement
    # (and trust) any particular normalisation table. A legitimate
    # internationalised domain should be supplied in its ASCII/punycode
    # (xn--...) form, which is what actually goes out over DNS anyway.
    if not host.isascii():
        return False, "non-ASCII hostname; encode to punycode before fetching"
    if host in BLOCKED_HOSTNAMES:
        return False, f"host {host!r} is blocked"

    ip = _host_as_ip(host)
    if ip is not None:
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False, f"address {ip} is not a public destination"
        # Carrier-grade NAT, not flagged by is_private on all versions.
        if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
            return False, "shared address space"

    return True, "ok"


def assert_fetch_allowed(url: str) -> None:
    allowed, reason = is_fetch_allowed(url)
    if not allowed:
        raise BlockedURL(f"{url}: {reason}")
