"""Postgres access: migrations, and transactions that run as the signed-in user.

    python -m bolagsvakt.db migrate            # apply new migrations/*.sql in order

DATABASE_URL picks the database (default: local `bolagsvakt`). The same migrations run on a
plain Postgres and on Supabase.
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///bolagsvakt")


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply each migrations/NNN_*.sql not yet recorded, each in its own transaction."""
    conn.execute("create table if not exists schema_migrations (name text primary key, "
                 "applied_at timestamptz not null default now())")
    conn.commit()
    done = {r[0] for r in conn.execute("select name from schema_migrations")}
    applied = []
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("insert into schema_migrations (name) values (%s)", [path.name])
        applied.append(path.name)
    return applied


@contextmanager
def as_user(conn: psycopg.Connection, user_id: str):
    """A transaction in which row-level security sees `user_id`: our own `bolagsvakt_app` role
    plus the user's id in request.jwt.claims (both reset when the transaction ends)."""
    with conn.transaction():
        conn.execute("set local role bolagsvakt_app")
        conn.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps({"sub": user_id})])
        yield conn


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["migrate"])
    p.parse_args(argv)
    with psycopg.connect(DATABASE_URL) as conn:
        print("applied:", migrate(conn) or "nothing new")


if __name__ == "__main__":
    main()
