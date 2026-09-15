"""A dropped archetype detection must not clobber the founder's explicit
target scope -- every chair builds a `Scope` from it."""
from jury.graph.nodes.archetype import detect_archetype
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports


async def test_failed_detection_leaves_the_founders_target_scope_alone():
    transports = Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                            fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)
    state = {"pitch": "An unrecorded pitch with no fixture, so detection cannot succeed.",
             "target_scope": {"geo": "US", "segment": "smb"}}

    out = await detect_archetype(state, transports=transports, trace=None)

    assert out["archetype"] is None
    assert out["archetype_confidence"] == 0.0
    assert "target_scope" not in out
