"""Extra redirect-chain coverage beyond the batch brief's single-hop case.

A guard that only re-validates the first `Location` header is not enough: a
relative Location, or a redirect to a URL that itself redirects again, are
both standard ways to smuggle a private address past a check that only looks
at the request the caller made. These pin that every hop is independently
re-validated before being followed.
"""
import httpx
import respx

from jury.retrieval.fetch import LiveFetchClient
from jury.settings import Settings
from jury.transport.kv import MemoryKV


def client():
    return LiveFetchClient(Settings(_env_file=None), MemoryKV())


@respx.mock
async def test_a_protocol_relative_redirect_to_a_private_address_is_refused():
    respx.get("https://evil.test/r").mock(
        return_value=httpx.Response(302, headers={"location": "//127.0.0.1/x"}))
    r = await client().fetch("https://evil.test/r")
    assert r.status >= 400


@respx.mock
async def test_a_redirect_chain_that_ends_at_a_private_address_is_refused():
    respx.get("https://evil.test/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.test/b"}))
    respx.get("https://evil.test/b").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"}))
    r = await client().fetch("https://evil.test/a")
    assert r.status >= 400


@respx.mock
async def test_a_redirect_chain_that_ends_at_a_legitimate_page_is_followed():
    respx.get("https://evil.test/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.test/b"}))
    respx.get("https://evil.test/b").mock(
        return_value=httpx.Response(
            200, html="<main><p>Legit content here that is real.</p></main>"))
    r = await client().fetch("https://evil.test/a")
    assert r.status == 200
    assert "Legit" in r.text
