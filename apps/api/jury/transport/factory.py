"""Transport selection. One place decides live vs fixture."""
from jury.settings import Settings
from jury.transport.fixtures import (
    FixtureFetchClient,
    FixtureLLMClient,
    FixtureSearchClient,
)
from jury.transport.kv import MemoryKV, UpstashKV
from jury.transport.protocols import Transports


def build_transports(settings: Settings) -> Transports:
    kv = (UpstashKV(settings.upstash_redis_rest_url, settings.upstash_redis_rest_token)
          if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token
          else MemoryKV())

    if settings.offline:
        return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                          fetch=FixtureFetchClient(), kv=kv, offline=True)

    # Imported lazily so an offline environment never needs the live deps.
    # NOTE: live search and fetch do not exist until Phase 3. Importing them
    # here in Phase 2 would raise ImportError, so each is resolved separately
    # and falls back to its fixture until Phase 3 extends this function.
    from jury.llm.gateway import LiveLLMClient

    try:
        from jury.retrieval.search import LiveSearchClient
        search = LiveSearchClient(settings, kv)
    except ImportError:
        search = FixtureSearchClient()

    try:
        from jury.retrieval.fetch import LiveFetchClient
        fetch = LiveFetchClient(settings, kv)
    except ImportError:
        fetch = FixtureFetchClient()

    return Transports(llm=LiveLLMClient(settings), search=search,
                      fetch=fetch, kv=kv, offline=False)
