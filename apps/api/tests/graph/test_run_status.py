"""`runs.status` tracks the pipeline -- the only signal a polling client has
for where a run is. Pauses at the hearing as `hearing`; ends as `complete`."""
from jury.db.repositories import RunRepo
from jury.graph.build import resume_hearing, run_initial

from tests.graph.conftest import cleanup_run, seed_project_run
from tests.graph.test_graph import CLASSES, PITCH, TARGET, _transports


async def test_run_status_moves_from_hearing_to_complete(real_pool):
    seed = await seed_project_run(real_pool, target_scope=TARGET, suffix="-status")
    transports = _transports()
    runs = RunRepo(real_pool)
    try:
        state = await run_initial(seed["project_id"], seed["run_id"], PITCH, TARGET,
                                  transports=transports, pool=real_pool, classes=CLASSES)
        assert (await runs.get(seed["run_id"]))["status"] == "hearing"

        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        row = await runs.get(seed["run_id"])
        assert row["status"] == "complete"
        assert row["completed_at"] is not None
    finally:
        await cleanup_run(real_pool, seed["run_id"])
