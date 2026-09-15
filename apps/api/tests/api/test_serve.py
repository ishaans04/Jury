"""The launcher must never run the app on a ProactorEventLoop: psycopg's
async driver cannot use one, so every database call would fail on Windows."""
import asyncio

from jury.api import serve


def test_launcher_runs_the_app_on_a_selector_event_loop():
    assert serve.loop_factory() is asyncio.SelectorEventLoop


def test_a_selector_loop_supports_psycopg_async_connections():
    loop = serve.loop_factory()()
    try:
        assert not isinstance(loop, getattr(asyncio, "ProactorEventLoop", ()))
    finally:
        loop.close()
