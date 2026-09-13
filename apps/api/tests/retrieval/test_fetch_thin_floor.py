"""Fix round 1 (code review): the thin-extraction check was pure emptiness
(retry tier 2 only when nothing at all was recovered). The reviewer noted a
small nonzero floor satisfies every existing fixture just as well while also
catching the class of page whose only server-rendered text is a cookie-banner
or an "enable JavaScript to continue" placeholder -- a few words, technically
nonzero, still not a page worth accepting as fetched. `_THIN_TEXT_FLOOR = 20`
in fetch.py implements that floor.
"""
import httpx
import respx

from jury.retrieval.fetch import JINA_PREFIX, LiveFetchClient
from jury.settings import Settings
from jury.transport.kv import MemoryKV


def client():
    return LiveFetchClient(Settings(_env_file=None), MemoryKV())


@respx.mock
async def test_a_short_junk_placeholder_still_falls_back_to_the_reader():
    respx.get("https://spa.test/pricing").mock(
        return_value=httpx.Response(200, html="<html><body><p>Enable JS</p></body></html>"))
    respx.get(f"{JINA_PREFIX}https://spa.test/pricing").mock(
        return_value=httpx.Response(200, text="# Pricing\n\nPro plan costs 499 INR."))
    r = await client().fetch("https://spa.test/pricing")
    assert "499" in r.text
