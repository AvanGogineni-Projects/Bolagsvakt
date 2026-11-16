"""Publish the pipeline's output to Postgres for the app, in one transaction.

    python -m bolagsvakt.publish

Companies are upserted, never deleted (watchlists point at them). Scores are replaced as a
whole. Events are appended; a rerun of the same week adds nothing. Users see either last week's
data or this week's, never a mix.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import duckdb
import psycopg

from bolagsvakt.db import DATABASE_URL

DATA = Path(os.environ.get("BOLAGSVAKT_DATA", "data"))
MODEL = Path(__file__).resolve().parents[2] / "models" / "risk_v1.json"
# Deregistered companies older than this are left out: nobody watches them, and they would
# double the table. shortcut: fixed window; make it a setting if customers ask for older history.
KEEP_DEREGISTERED_YEARS = 2

COMPANIES_SQL = """
with procs as (
    select org_nr,
           case when bool_or(code = 'KK-AVOMFO') then 'in_bankruptcy'
                when bool_or(code = 'FR-AVOMFO') then 'in_reconstruction'
                when bool_or(code = 'LI-AVOMFO') then 'in_liquidation' end as status
    from read_parquet($procs) group by org_nr)
select c.org_nr, c.name, c.legal_form, c.city, c.registered_on, c.deregistered_on,
       case when c.deregistered_on is not null then 'deregistered'
            else coalesce(p.status, 'active') end as status
from read_parquet($companies) c left join procs p using (org_nr)
where (c.deregistered_on is null or c.deregistered_on >= $cutoff)
qualify row_number() over (partition by c.org_nr order by c.name_seq) = 1  -- one row per org number
"""


def _rows(sql: str, **params) -> list[tuple]:
    return duckdb.execute(sql, params).fetchall()


def publish(conn: psycopg.Connection, registry: Path, scores: Path, events: Path, model: dict,
            snapshot: dt.date) -> dict[str, int]:
    cutoff = snapshot.replace(year=snapshot.year - KEEP_DEREGISTERED_YEARS)
    companies = _rows(COMPANIES_SQL, companies=str(registry / "companies.parquet"),
                      procs=str(registry / "proceedings.parquet"), cutoff=cutoff)
    score_rows = _rows("select org_nr, fiscal_end, filed_on, probability, times_average, reasons "
                       "from read_parquet($p)", p=str(scores)) if scores.exists() else []
    event_rows = _rows("select distinct snapshot_date, org_nr, event, coalesce(detail, '') "
                       "from read_parquet($p)", p=str(events)) if events.exists() else []
    with conn.transaction():
        # A weekly bulk load of ~1M rows outlasts limits meant for interactive queries (Supabase:
        # 2 min). `local` lifts it for this transaction only; the API's queries keep theirs.
        conn.execute("set local statement_timeout = 0")
        conn.execute("create temp table stage_companies (like companies) on commit drop")
        conn.execute("create temp table stage_scores (like risk_scores) on commit drop")
        conn.execute("create temp table stage_events (like company_events) on commit drop")
        with conn.cursor().copy("copy stage_companies from stdin") as cp:
            for r in companies:
                cp.write_row(r)
        with conn.cursor().copy("copy stage_scores (org_nr, fiscal_end, filed_on, probability, "
                                "times_average, reasons, model_version) from stdin") as cp:
            for r in score_rows:
                cp.write_row((*r, model["version"]))
        with conn.cursor().copy("copy stage_events from stdin") as cp:
            for r in event_rows:
                cp.write_row(r)
        conn.execute("""insert into companies select * from stage_companies
                        on conflict (org_nr) do update set name = excluded.name, legal_form = excluded.legal_form,
                          city = excluded.city, registered_on = excluded.registered_on,
                          deregistered_on = excluded.deregistered_on, status = excluded.status
                        -- only rows that changed: a week touches a few thousand, not all 1M
                        where companies is distinct from excluded""")
        conn.execute("delete from risk_scores")
        n_scores = conn.execute("insert into risk_scores select s.* from stage_scores s "
                                "join companies c using (org_nr)").rowcount
        n_events = conn.execute("insert into company_events select e.* from stage_events e "
                                "join companies c using (org_nr) on conflict do nothing").rowcount
        conn.execute("insert into publish_runs (registry_snapshot, model_version, companies, scores, events) "
                     "values (%s, %s, %s, %s, %s)", [snapshot, model["version"], len(companies), n_scores, n_events])
    return {"companies": len(companies), "scores": n_scores, "new_events": n_events}


def main() -> None:
    registry = max((DATA / "silver" / "registry").iterdir())
    with psycopg.connect(DATABASE_URL) as conn:
        print(publish(conn, registry, DATA / "gold" / "risk_scores.parquet",
                      DATA / "state" / "registry" / "events.parquet", json.loads(MODEL.read_text()),
                      dt.date.fromisoformat(registry.name)))


if __name__ == "__main__":
    main()
