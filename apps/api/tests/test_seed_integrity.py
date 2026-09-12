import psycopg
import pytest

DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DEEP = {"marketplace", "subscription_saas", "d2c"}
SHALLOW = {"services", "ad_consumer", "hardware"}


@pytest.fixture()
def conn():
    with psycopg.connect(DSN, autocommit=True) as c:
        yield c


def test_all_six_archetypes_seeded(conn):
    with conn.cursor() as cur:
        cur.execute("select distinct archetype from assumption_classes")
        assert {r[0] for r in cur.fetchall()} == DEEP | SHALLOW


def test_deep_archetypes_have_ten_classes(conn):
    with conn.cursor() as cur:
        cur.execute("select archetype, count(*) from assumption_classes "
                    "where archetype = any(%s) group by archetype", (list(DEEP),))
        assert dict(cur.fetchall()) == {a: 10 for a in DEEP}


def test_shallow_archetypes_have_five_classes(conn):
    with conn.cursor() as cur:
        cur.execute("select archetype, count(*) from assumption_classes "
                    "where archetype = any(%s) group by archetype", (list(SHALLOW),))
        assert dict(cur.fetchall()) == {a: 5 for a in SHALLOW}


def test_every_archetype_has_at_least_three_blocking_classes(conn):
    """A denominator with no blocking classes cannot gate a verdict."""
    with conn.cursor() as cur:
        cur.execute("select archetype, count(*) from assumption_classes "
                    "where crit_weight = 1.0 group by archetype")
        for archetype, n in cur.fetchall():
            assert n >= 3, f"{archetype} has only {n} blocking classes"


def test_class_keys_are_archetype_prefixed(conn):
    """Prefixing makes the coverage join unambiguous and keys self-documenting."""
    prefix = {"marketplace": "marketplace", "subscription_saas": "saas", "d2c": "d2c",
              "services": "services", "ad_consumer": "ad", "hardware": "hardware"}
    with conn.cursor() as cur:
        cur.execute("select key, archetype from assumption_classes")
        for key, archetype in cur.fetchall():
            assert key.startswith(prefix[archetype] + "."), key


def test_questions_are_questions(conn):
    with conn.cursor() as cur:
        cur.execute("select key, question from assumption_classes")
        for key, question in cur.fetchall():
            assert question.endswith("?"), key
