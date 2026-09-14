"""SSE for transient cross-exam tokens. Task 5.6. PRD §10.2.

PRD §10.2, verbatim: "SSE is retained for exactly one thing -- token-level
streaming of cross-examination prose, which is transient and not
persisted as evidence." Every other piece of state the UI needs -- a
chair "speaking" is really a persisted row -- reaches it through Supabase
Realtime on the ledger tables, not through this router.

That scope is deliberately narrow in two directions:

* This is the *only* SSE route in the app. There is no `GET
  /runs/{id}/evidence/stream` or anything like it -- evidence is durable,
  and durable state goes through Realtime, never through a socket a
  client can lose bytes on.
* Nothing here writes to Postgres. The generator below never touches
  `evidence_items` (or any other table) -- it only reads `runs.status` to
  know when to stop, and emits `text/event-stream` bytes. A run's actual
  outcome lives in the `runs` row, not in whether a browser tab happens to
  have this connection open -- PRD §10.2's own argument against relying on
  SSE for state ("it loses on reconnect") -- so a client that never opens
  this stream, or drops it mid-run, has no effect on the run at all.

The stream stays open only while the run is actually in `cross_exam`
(heartbeating every `_HEARTBEAT_SECONDS` so intermediaries don't time it
out) and closes itself the moment the run leaves that phase -- reconciled
early, moved on to economics, failed, whatever -- or the client
disconnects, whichever comes first. There is deliberately no real-token
producer wired in yet (that is the chair-side cross-exam node's job, a
separate concern from this route's transport contract); this closes
cleanly with nothing further to say rather than hanging open.
"""
import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from jury.api.deps import get_user_pool
from jury.db.repositories import RunRepo

router = APIRouter(tags=["stream"])

_HEARTBEAT_SECONDS = 15
_STREAMABLE_STATUSES = {"cross_exam"}


async def _cross_exam_events(request: Request, run_id: str, pool) -> AsyncIterator[bytes]:
    yield b": stream-open\n\n"
    try:
        while True:
            if await request.is_disconnected():
                return
            row = await RunRepo(pool).get(run_id)
            if row is None or row["status"] not in _STREAMABLE_STATUSES:
                return
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            yield b": heartbeat\n\n"
    except asyncio.CancelledError:
        # A dropped connection cancels this generator from the outside.
        # Nothing about the run depends on this stream staying open, so
        # there is nothing to clean up beyond returning quietly.
        return


@router.get("/runs/{run_id}/cross-exam/stream")
async def stream_cross_exam(run_id: str, request: Request,
                            pool=Depends(get_user_pool)) -> StreamingResponse:
    return StreamingResponse(
        _cross_exam_events(request, run_id, pool),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
