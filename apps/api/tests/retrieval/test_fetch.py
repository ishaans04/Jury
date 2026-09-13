import httpx
import pytest
import respx

from jury.retrieval.extract import chunk, extract_text
from jury.retrieval.fetch import JINA_PREFIX, LiveFetchClient
from jury.retrieval.ssrf import BlockedURL
from jury.settings import Settings
from jury.transport.kv import MemoryKV

pytestmark = pytest.mark.network


def client(kv=None):
    return LiveFetchClient(Settings(_env_file=None), kv or MemoryKV())


@respx.mock
async def test_a_normal_page_is_fetched_and_extracted():
    respx.get("https://x.test/pricing").mock(
        return_value=httpx.Response(200, html="<html><body><main>"
                                    "<h1>Pricing</h1><p>Starter is 149 INR per month.</p>"
                                    "</main></body></html>"))
    r = await client().fetch("https://x.test/pricing")
    assert r.status == 200
    assert "149" in r.text


@respx.mock
async def test_thin_extraction_falls_back_to_jina_reader():
    """PRD §16.1 tier 2. Jina Reader is free and needs no key."""
    respx.get("https://js.test/pricing").mock(
        return_value=httpx.Response(200, html="<html><body><div id='root'></div></body></html>"))
    respx.get(f"{JINA_PREFIX}https://js.test/pricing").mock(
        return_value=httpx.Response(200, text="# Pricing\n\nPro plan costs 499 INR."))
    r = await client().fetch("https://js.test/pricing")
    assert "499" in r.text


@respx.mock
async def test_a_403_is_returned_as_a_rejected_source_not_an_exception():
    """PRD §18: 'Page fetch 403 / paywall -> claim rejected at insert; logged as
    a rejected source.' Degrade to less evidence, never crash."""
    respx.get("https://paywall.test/a").mock(return_value=httpx.Response(403))
    r = await client().fetch("https://paywall.test/a")
    assert r.status == 403 and r.text == ""


@respx.mock
async def test_a_404_is_returned_as_a_rejected_source():
    respx.get("https://gone.test/a").mock(return_value=httpx.Response(404))
    assert (await client().fetch("https://gone.test/a")).status == 404


async def test_a_blocked_target_raises_before_any_socket_opens():
    with pytest.raises(BlockedURL):
        await client().fetch("http://169.254.169.254/latest/meta-data/")


@respx.mock
async def test_the_same_canonical_url_is_fetched_once_within_the_ttl():
    """PRD §16.1: every fetch is deduplicated in Redis by canonical URL, 24h TTL."""
    route = respx.get("https://x.test/p").mock(
        return_value=httpx.Response(200, html="<p>Body text that is long enough.</p>"))
    kv = MemoryKV()
    c = client(kv)
    await c.fetch("https://x.test/p")
    await c.fetch("https://x.test/p?utm_source=tw")   # same canonical url
    assert route.call_count == 1


@respx.mock
async def test_a_redirect_to_a_private_address_is_refused():
    respx.get("https://evil.test/r").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:22/"}))
    r = await client().fetch("https://evil.test/r")
    assert r.status >= 400


# ── extraction and chunking, no network ────────────────────────────────────
@pytest.mark.parametrize("html,needle", [
    ("<html><body><article><p>Pro plan is 999 INR.</p></article></body></html>", "999"),
    ("<html><body><main><p>Free tier includes 3 seats.</p></main></body></html>", "3 seats"),
])
def test_extract_text_pulls_the_body(html, needle):
    assert needle in extract_text(html, "https://x.test/")


def test_extract_text_drops_script_and_nav_noise():
    html = ("<html><body><nav>Home About</nav><script>var x=1</script>"
            "<main><p>The real content is a price of 250 INR.</p></main></body></html>")
    out = extract_text(html, "https://x.test/")
    assert "250" in out and "var x=1" not in out


def test_chunking_respects_size_and_overlaps():
    text = " ".join(f"word{i}" for i in range(600))
    chunks = chunk(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert chunks[0][-10:] in chunks[1]        # overlap preserved


def test_chunking_a_short_text_yields_one_chunk():
    assert chunk("short", size=200) == ["short"]
