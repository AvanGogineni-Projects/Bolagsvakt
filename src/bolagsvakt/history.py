"""Weekly snapshots -> SCD2 company history + an append-only event log.

Bolagsverket publishes only the current state of each company. Change history (and so every
alert the product sends) exists only because we keep each weekly snapshot and diff it against the
previous one here.

Files in `state_dir`:
  history.parquet      one row per company version, valid_from <= t < valid_to (null = current)
  proceedings.parquet  the proceedings of the last applied snapshot
  events.parquet       what changed, one row per (snapshot, company, event)
  state.json           the last applied snapshot date

The first snapshot is the baseline: it fills history but emits no events (nothing "happened";
we just started watching).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import duckdb

KEY = ["org_nr", "name_seq"]
TRACKED = ["name", "legal_form", "deregistered_on", "deregistration_reason", "description",
           "street", "care_of", "city", "postcode"]
# field-level events: (event name, columns whose change triggers it)
FIELD_EVENTS = [
    ("name_changed", ["name"]),
    ("legal_form_changed", ["legal_form"]),
    ("address_changed", ["street", "care_of", "city", "postcode"]),
    ("description_changed", ["description"]),
]
EVENT_COLUMNS = "snapshot_date date, org_nr varchar, name_seq integer, event varchar, detail varchar"


class OutOfOrder(Exception):
    """A snapshot older than the last applied one would rewrite history; refuse it."""


def _hash_expr() -> str:
    # '\x1f' separator and a null marker so ('a', null) and (null, 'a') hash differently
    return "md5(concat_ws(chr(31), " + ", ".join(f"coalesce(cast({c} as varchar), chr(0))" for c in TRACKED) + "))"


def _write(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> None:
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"copy ({sql}) to '{tmp}' (format parquet)")
    tmp.replace(path)


def apply_snapshot(silver_dir: Path, snapshot: dt.date, state_dir: Path) -> dict[str, int]:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    last = dt.date.fromisoformat(json.loads(state_file.read_text())["last_snapshot"]) if state_file.exists() else None
    if last is not None and snapshot == last:
        return {"skipped": 1}  # idempotent rerun
    if last is not None and snapshot < last:
        raise OutOfOrder(f"snapshot {snapshot} is older than last applied {last}")

    con = duckdb.connect()
    con.execute(f"create temp table curr as select *, {_hash_expr()} as row_hash "
                f"from '{silver_dir / 'companies.parquet'}'")
    con.execute(f"create temp table curr_proc as select * from '{silver_dir / 'proceedings.parquet'}'")
    con.execute(f"create temp table events ({EVENT_COLUMNS})")
    d = f"date '{snapshot}'"
    cols = ", ".join(KEY + TRACKED)
    on = " and ".join(f"h.{k} = c.{k}" for k in KEY)

    if last is None:
        con.execute(f"create temp table history as select {cols}, row_hash, {d} as valid_from, "
                    f"cast(null as date) as valid_to from curr")
    else:
        con.execute(f"create temp table history as select * from '{state_dir / 'history.parquet'}'")
        con.execute(f"create temp table prev_proc as select * from '{state_dir / 'proceedings.parquet'}'")
        con.execute("create temp view open_h as select * from history where valid_to is null")
        # company-level events
        con.execute(f"""insert into events select {d}, c.org_nr, c.name_seq, 'registered', c.name
                        from curr c anti join open_h h on {on}""")
        con.execute(f"""insert into events select {d}, h.org_nr, h.name_seq, 'removed_from_register', h.name
                        from open_h h anti join curr c on {on}""")
        con.execute(f"""insert into events select {d}, c.org_nr, c.name_seq, 'deregistered',
                        concat_ws(' ', c.deregistered_on, c.deregistration_reason)
                        from curr c join open_h h on {on}
                        where h.deregistered_on is null and c.deregistered_on is not null""")
        for event, fields in FIELD_EVENTS:
            changed = " or ".join(f"h.{f} is distinct from c.{f}" for f in fields)
            old = " || ', ' || ".join(f"coalesce(h.{f}, '')" for f in fields)
            new = " || ', ' || ".join(f"coalesce(c.{f}, '')" for f in fields)
            con.execute(f"""insert into events select {d}, c.org_nr, c.name_seq, '{event}',
                            {old} || ' -> ' || {new}
                            from curr c join open_h h on {on} where {changed}""")
        # proceedings: a (company, code) pair that appears or disappears
        pk = "org_nr, name_seq, code"
        con.execute(f"""insert into events select {d}, org_nr, name_seq, 'proceeding_started',
                        concat_ws(' ', code, since) from curr_proc where ({pk}) not in (select {pk} from prev_proc)""")
        con.execute(f"""insert into events select {d}, org_nr, name_seq, 'proceeding_ended', code
                        from prev_proc where ({pk}) not in (select {pk} from curr_proc)""")
        # SCD2: close changed or vanished versions, open new ones
        con.execute(f"""create temp table changed as select c.* from curr c
                        left join open_h h on {on} where h.org_nr is null or h.row_hash <> c.row_hash""")
        con.execute(f"""update history h set valid_to = {d} where valid_to is null and (
                          exists (select 1 from changed c where {on})
                          or not exists (select 1 from curr c where {on}))""")
        con.execute(f"insert into history select {cols}, row_hash, {d}, null from changed")

    _write(con, "select * from history order by org_nr, name_seq, valid_from", state_dir / "history.parquet")
    _write(con, "select * from curr_proc", state_dir / "proceedings.parquet")
    old_events = (f"select * from '{state_dir / 'events.parquet'}' union all "
                  if (state_dir / "events.parquet").exists() else "")
    _write(con, f"{old_events}select * from events", state_dir / "events.parquet")
    # state last: if anything above failed, the rerun redoes this snapshot from scratch
    state_file.write_text(json.dumps({"last_snapshot": snapshot.isoformat()}))
    stats = {r[0]: r[1] for r in con.execute("select event, count(*) from events group by 1").fetchall()}
    stats["versions"] = con.execute("select count(*) from history").fetchone()[0]
    return stats
