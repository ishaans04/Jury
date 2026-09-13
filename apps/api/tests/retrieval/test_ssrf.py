import pytest

from jury.retrieval.ssrf import (
    BLOCKED_HOSTNAMES,
    BlockedURL,
    assert_fetch_allowed,
    is_fetch_allowed,
)


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1:8000/", "http://0.0.0.0/",
    "http://[::1]/", "http://10.1.2.3/", "http://172.16.0.5/",
    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://100.64.0.1/",
])
def test_private_and_metadata_targets_are_blocked(url):
    """Model-selected URLs must never reach infrastructure."""
    allowed, _ = is_fetch_allowed(url)
    assert allowed is False


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://x.test/f", "gopher://x.test/",
    "data:text/html,<script>", "javascript:alert(1)",
])
def test_non_http_schemes_are_blocked(url):
    assert is_fetch_allowed(url)[0] is False


@pytest.mark.parametrize("url", [
    "https://example.test/pricing", "http://news.ycombinator.com/item?id=1",
    "https://web.archive.org/web/2020/https://x.test/",
])
def test_ordinary_public_urls_are_allowed(url):
    assert is_fetch_allowed(url)[0] is True


def test_decimal_encoded_loopback_is_blocked():
    """2130706433 == 127.0.0.1. A naive string check would miss this."""
    assert is_fetch_allowed("http://2130706433/")[0] is False


def test_octal_and_hex_encoded_loopback_is_blocked():
    assert is_fetch_allowed("http://0x7f000001/")[0] is False


def test_credentials_in_the_url_are_blocked():
    assert is_fetch_allowed("https://user:pass@example.test/")[0] is False


def test_the_reason_is_reported_so_it_can_be_traced():
    allowed, reason = is_fetch_allowed("http://169.254.169.254/")
    assert allowed is False and reason


def test_assert_helper_raises_blockedurl():
    with pytest.raises(BlockedURL):
        assert_fetch_allowed("http://127.0.0.1/")
    assert assert_fetch_allowed("https://example.test/") is None


# --- Extra coverage beyond the brief: inet_aton-style bypass forms that a
# strict `ipaddress.ip_address()` call rejects outright, but that curl,
# glibc's `inet_aton`, and other production HTTP stacks still resolve to a
# concrete loopback/private address. If `_host_as_ip` only tried
# `ipaddress.ip_address` plus a whole-string integer parse (decimal/hex), all
# of these would slip through as "not a recognised IP" and fall through to
# being allowed as an ordinary hostname.

@pytest.mark.parametrize("url", [
    "http://0177.0.0.1/",       # dotted-octal per octet -> 127.0.0.1
    "http://0x7f.0.0.1/",       # dotted-hex per octet -> 127.0.0.1
    "http://127.1/",            # shorthand, last octet absorbs the rest -> 127.0.0.1
    "http://0300.0250.1.1/",    # dotted-octal -> 192.168.1.1 (private)
])
def test_encoded_dotted_and_shorthand_loopback_forms_are_blocked(url):
    assert is_fetch_allowed(url)[0] is False


def test_ipv6_mapped_ipv4_loopback_is_blocked():
    """`::ffff:127.0.0.1` is IPv4-mapped IPv6. Python's `ipaddress` already
    classifies this correctly as loopback, so this is a regression guard
    rather than evidence of a gap."""
    assert is_fetch_allowed("http://[::ffff:127.0.0.1]/")[0] is False


def test_ipv6_mapped_ipv4_metadata_is_blocked():
    assert is_fetch_allowed("http://[::ffff:169.254.169.254]/")[0] is False


def test_bare_integer_exceeding_ipv4_range_is_not_mistaken_for_a_private_ip():
    """Not a bypass: a decimal string over 2**32-1 can't denote any IPv4
    address, and real resolvers (verified via inet_aton) reject it outright
    too. It falls through to hostname handling, which is correct because no
    literal IP is actually being expressed."""
    allowed, _ = is_fetch_allowed("http://4294967296/")
    assert allowed is True


# --- Round-1 fix: a trailing dot bypassed every check, because neither the
# exact-string blocklist nor the IP-literal parser canonicalised the host
# first. A trailing dot marks a DNS name as already fully-qualified, and
# standard resolvers treat "localhost." identically to "localhost" -- so
# every one of these six previously returned (True, "ok").

@pytest.mark.parametrize("url", [
    "http://localhost./admin",
    "http://metadata./x",
    "http://metadata.google.internal./x",
    "http://instance-data./x",
    "http://169.254.169.254./latest/meta-data/",
    "http://127.0.0.1./",
])
def test_a_trailing_dot_does_not_bypass_the_blocklist(url):
    assert is_fetch_allowed(url)[0] is False


def test_multiple_trailing_dots_do_not_bypass_the_blocklist():
    assert is_fetch_allowed("http://localhost../admin")[0] is False
    assert is_fetch_allowed("http://169.254.169.254../x")[0] is False


@pytest.mark.parametrize("host", sorted(BLOCKED_HOSTNAMES))
def test_every_blocked_hostname_is_still_blocked_with_a_trailing_dot(host):
    """A future addition to BLOCKED_HOSTNAMES should inherit trailing-dot
    protection automatically, rather than needing its own bypass test."""
    assert is_fetch_allowed(f"http://{host}./x")[0] is False
    assert is_fetch_allowed(f"http://{host}../x")[0] is False


def test_a_fullwidth_homoglyph_of_a_blocked_hostname_is_rejected():
    """'lｏcalhost' (fullwidth Latin small letter O, U+FF4F) is not the
    literal string 'localhost' and isn't caught by exact blocklist
    comparison -- but Python's own stdlib IDNA2003/Nameprep codec folds it
    down to the ASCII bytes b'localhost' on encode, so a client that IDNA-
    encodes before connecting would still reach loopback. Verified directly:
    'lｏcalhost'.encode('idna') == b'localhost'. Rather than trying to
    correctly replicate (and trust) any particular normalisation table, the
    guard rejects non-ASCII hostnames outright."""
    assert "lｏcalhost".encode("idna") == b"localhost"  # documents the risk
    allowed, reason = is_fetch_allowed("http://lｏcalhost/x")
    assert allowed is False
    assert "ascii" in reason.lower()


def test_non_ascii_hostnames_are_rejected_even_when_not_a_known_alias():
    """The guard doesn't try to detect aliasing -- it refuses all non-ASCII
    hosts, which closes the whole class rather than one example of it."""
    assert is_fetch_allowed("http://例.test/x")[0] is False
