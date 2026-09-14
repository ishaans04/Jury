"""The version node. Task 6.2. PRD §9, §16.8.

Writes one immutable ledger version per run: a self-contained snapshot
(`jury.db.snapshot.build_snapshot`, Task 6.1) plus a computed causal delta
against the previous version (`jury.engines.diff.compute_diff`, reused
verbatim -- this module never reimplements the diff). Version 1's diff is
always empty (`compute_diff(None, snapshot) == []`); every later version's
diff is the delta from the immediately preceding snapshot.

Versions are dense (1, 2, 3, ...), monotonic, and an existing version is
never overwritten -- the actual version-number arithmetic, the `for update`
lock against races, and the UniqueViolation retry all live in
`LedgerVersionRepo.create_next_version` (jury/db/repositories.py is "the
only module that writes SQL", spec §6; this node orchestrates, it does not
issue SQL of its own). `ledger_versions` additionally gets the same P6-style
database-level immutability `evidence_items` has
(supabase/migrations/0010_ledger_versions_immutable.sql) -- a stored version
cannot be rewritten even by a caller that bypasses this node entirely.
"""
import dataclasses
from dataclasses import dataclass

from jury.db.repositories import LedgerVersionRepo
from jury.db.snapshot import build_snapshot
from jury.engines.diff import compute_diff
from jury.graph.state import RunState
from jury.tracing.events import TraceSink

NODE = "version"


@dataclass(slots=True)
class VersionRepos:
    ledger_version: LedgerVersionRepo


async def write_version(state: RunState, *, pool, repos: VersionRepos,
                        trace: TraceSink | None = None) -> dict:
    """Returns `{"version": int, "diff": list[dict]}`.

    Note this is the version node's own direct return shape (per the batch
    brief), not a partial `RunState` update the way every other node in this
    package returns one -- `write_version` is not yet wired into
    `jury.graph.build.build_graph`'s topology (that wiring is out of this
    batch's scope; the module docstring there still says "the version node
    is Phase 6").
    """
    if trace is not None:
        await trace.emit(node=NODE, event="node_start")

    project_id, run_id = state["project_id"], state["run_id"]

    previous = await repos.ledger_version.latest_for_project(project_id)
    snapshot = await build_snapshot(pool, project_id, run_id)

    previous_snapshot = previous["snapshot"] if previous is not None else None
    diff_entries = compute_diff(previous_snapshot, snapshot)
    diff = [dataclasses.asdict(entry) for entry in diff_entries]

    version = await repos.ledger_version.create_next_version(
        project_id, run_id, snapshot, diff)

    if trace is not None:
        await trace.emit(node=NODE, event="node_end")

    return {"version": version, "diff": diff}
