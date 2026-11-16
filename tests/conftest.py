import os

import psycopg
import pytest

from bolagsvakt.db import migrate

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql:///bolagsvakt_test")


@pytest.fixture
def db():
    """A freshly migrated empty schema per test (connection as the owner; tests switch to
    the `authenticated` role with db.as_user to exercise row-level security)."""
    try:
        conn = psycopg.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no test Postgres (set TEST_DATABASE_URL)")
    conn.execute("drop schema if exists public cascade; create schema public; "
                 "grant usage on schema public to public")
    conn.commit()
    migrate(conn, local=True)
    conn.commit()
    yield conn
    conn.close()
