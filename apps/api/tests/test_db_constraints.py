import psycopg
import pytest


def test_position_deltas_chair_is_constrained_to_the_five_chairs(conn):
    """Chairs are a closed set; an unconstrained value would render as a
    broken conceding-chair label in the conflict UI."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "insert into position_deltas (conflict_id, chair, before, after, reason) "
                "values (gen_random_uuid(), 'Visionary', 'a', 'b', 'r')")
