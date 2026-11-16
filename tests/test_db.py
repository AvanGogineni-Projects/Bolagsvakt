import datetime as dt
import uuid

import duckdb
import psycopg
import pytest

from bolagsvakt.db import as_user, migrate
from bolagsvakt.publish import publish

ALICE, BOB = str(uuid.uuid4()), str(uuid.uuid4())


def seed_companies(db, *org_nrs):
    with db.transaction():
        for nr in org_nrs:
            db.execute("insert into companies (org_nr, name, status) values (%s, %s, 'active')", [nr, f"Co {nr}"])


def test_migrations_are_recorded_and_not_reapplied(db):
    assert migrate(db, local=True) == []


def test_customers_cannot_see_each_others_watchlists(db):
    seed_companies(db, "5560000001", "5560000002")
    with as_user(db, ALICE):
        a = db.execute("select create_organization('Alice AB')").fetchone()[0]
        db.execute("insert into watchlist (org_id, org_nr) values (%s, '5560000001')", [a])
    with as_user(db, BOB):
        b = db.execute("select create_organization('Bob AB')").fetchone()[0]
        db.execute("insert into watchlist (org_id, org_nr) values (%s, '5560000002')", [b])
        # Bob sees only his own organisation and list, even with no WHERE clause at all
        assert db.execute("select org_nr from watchlist").fetchall() == [("5560000002",)]
        assert db.execute("select name from organizations").fetchall() == [("Bob AB",)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(db, BOB):
        db.execute("insert into watchlist (org_id, org_nr) values (%s, '5560000002')", [a])  # into Alice's org
    with as_user(db, BOB):
        assert db.execute("delete from watchlist where org_id = %s", [a]).rowcount == 0
    with as_user(db, ALICE):
        assert db.execute("select org_nr from watchlist").fetchall() == [("5560000001",)]


def test_memberships_only_via_create_organization(db):
    with as_user(db, ALICE):
        org = db.execute("select create_organization('Alice AB')").fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(db, BOB):
        db.execute("insert into memberships (org_id, user_id) values (%s, %s)", [org, BOB])  # join Alice's org
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        db.execute("set local role authenticated")
        db.execute("select create_organization('No user')")  # no JWT claims


def test_publish_is_atomic_idempotent_and_keeps_watchlisted_companies(db, tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    duckdb.sql("""select * from (values
        ('5560000001', 0, 'Alfa AB', 'AB-ORGFO', 'STOCKHOLM', date '2001-01-01', null::date),
        ('5560000002', 0, 'Beta AB', 'AB-ORGFO', 'LUND', date '2001-01-01', null::date),
        ('5560000003', 0, 'Gamma AB', 'AB-ORGFO', 'LUND', date '2001-01-01', date '2010-01-01'))
        t(org_nr, name_seq, name, legal_form, city, registered_on, deregistered_on)
        """).write_parquet(str(reg / "companies.parquet"))
    duckdb.sql("select * from (values ('5560000002', 0, 'KK-AVOMFO', date '2026-11-01')) "
               "t(org_nr, name_seq, code, since)").write_parquet(str(reg / "proceedings.parquet"))
    scores = tmp_path / "scores.parquet"
    duckdb.sql("select * from (values ('5560000001', date '2025-12-31', date '2026-03-01', 0.05, 2.5, "
               "['Made a loss this year'])) t(org_nr, fiscal_end, filed_on, probability, times_average, reasons)"
               ).write_parquet(str(scores))
    events = tmp_path / "events.parquet"
    duckdb.sql("select * from (values (date '2026-11-23', '5560000002', 0, 'proceeding_started', "
               "'KK-AVOMFO 2026-11-01')) t(snapshot_date, org_nr, name_seq, event, detail)"
               ).write_parquet(str(events))
    model = {"version": "risk_v1"}
    snap = dt.date(2026, 11, 23)

    assert publish(db, reg, scores, events, model, snap) == {"companies": 2, "scores": 1, "new_events": 1}
    assert publish(db, reg, scores, events, model, snap) == {"companies": 2, "scores": 1, "new_events": 0}
    status = dict(db.execute("select org_nr, status from companies").fetchall())
    assert status == {"5560000001": "active", "5560000002": "in_bankruptcy"}  # old deregistration left out

    # a publish that fails halfway (corrupt events file) leaves the previous week fully in place
    corrupt = tmp_path / "corrupt.parquet"
    corrupt.write_bytes(b"not parquet")
    with pytest.raises(duckdb.Error):
        publish(db, reg, scores, corrupt, model, snap)
    assert db.execute("select count(*) from risk_scores").fetchone()[0] == 1
    assert db.execute("select count(*) from publish_runs").fetchone()[0] == 2
