import pytest

from jury.tracing.events import EVENT_KINDS, MemoryTraceSink, traced


async def test_every_event_kind_matches_the_db_check_constraint():
    assert set(EVENT_KINDS) == {"node_start", "node_end", "llm_call", "tool_call",
                                "fetch", "error", "interrupt"}


async def test_traced_emits_start_and_end_with_latency():
    sink = MemoryTraceSink()

    @traced("archetype")
    async def node(state, *, trace):
        return {"ok": True}

    await node({}, trace=sink)
    kinds = [r["event"] for r in sink.rows]
    assert kinds == ["node_start", "node_end"]
    assert sink.rows[1]["latency_ms"] >= 0
    assert sink.rows[0]["node"] == "archetype"


async def test_traced_emits_an_error_row_and_reraises():
    sink = MemoryTraceSink()

    @traced("boom")
    async def node(state, *, trace):
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await node({}, trace=sink)
    kinds = [r["event"] for r in sink.rows]
    assert kinds == ["node_start", "error"]
    assert "nope" in sink.rows[1]["detail"]["error"]


async def test_llm_call_rows_carry_token_counts():
    """PRD §11.2 dec. 9: one row per tool call, latency, token count."""
    sink = MemoryTraceSink()
    await sink.emit(node="market", event="llm_call",
                    detail={"model": "groq/x", "prompt_tokens": 120,
                            "completion_tokens": 40}, latency_ms=310)
    row = sink.rows[0]
    assert row["detail"]["prompt_tokens"] == 120
    assert row["latency_ms"] == 310


async def test_an_unknown_event_kind_is_rejected_before_it_reaches_the_db():
    sink = MemoryTraceSink()
    with pytest.raises(ValueError):
        await sink.emit(node="market", event="vibes")


async def test_fetch_rows_record_url_and_status():
    sink = MemoryTraceSink()
    await sink.emit(node="market", event="fetch",
                    detail={"url": "https://x.test/p", "status": 200, "ms": 84})
    assert sink.rows[0]["detail"]["status"] == 200


async def test_interrupt_is_traceable_so_the_hearing_pause_is_visible():
    sink = MemoryTraceSink()
    await sink.emit(node="hearing", event="interrupt",
                    detail={"reason": "awaiting founder confirmation"})
    assert sink.rows[0]["event"] == "interrupt"


async def test_traced_passes_the_sink_through_so_a_node_can_emit_its_own_rows():
    """PRD §11.2 dec. 9: a node must be able to log its own llm_call/fetch
    rows -- traced() is not the only source of rows for that node."""
    sink = MemoryTraceSink()

    @traced("market")
    async def node(state, *, trace):
        await trace.emit(node="market", event="llm_call",
                         detail={"model": "groq/x"}, latency_ms=5)
        return "done"

    await node({}, trace=sink)
    kinds = [r["event"] for r in sink.rows]
    assert kinds == ["node_start", "llm_call", "node_end"]
