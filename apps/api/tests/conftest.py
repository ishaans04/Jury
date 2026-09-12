import os

import psycopg
import pytest

# Local Supabase Postgres started via `npx supabase start` (see supabase/config.toml).
# Overridable via DATABASE_URL for CI or a different local port.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture
def conn():
    """A DB connection wrapped in a transaction that is always rolled back,
    so constraint tests never leave rows behind in the local database."""
    connection = psycopg.connect(DATABASE_URL)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
