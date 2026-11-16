import os

import psycopg
import pytest

from bolagsvakt.db import migrate

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql:///bolagsvakt_test")


@pytest.fixture
def db():
    """A freshly migrated empty schema per test (connection as the owner; tests switch to the
    app's role with db.as_user to exercise row-level security). Supabase's built-in roles are
    created too, so tests can prove they get nothing."""
    try:
        conn = psycopg.connect(TEST_DB)
    except psycopg.OperationalError:
        pytest.skip("no test Postgres (set TEST_DATABASE_URL)")
    conn.execute("drop schema if exists public cascade; create schema public; "
                 "grant usage on schema public to public")
    conn.execute("""do $$ begin
        if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
        if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
        end $$""")
    conn.commit()
    migrate(conn)
    conn.commit()
    yield conn
    conn.close()
