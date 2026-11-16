"""Bolagsverket registry snapshot (bolagsverket_bulkfil.txt) -> typed silver tables.

The file is `;`-separated and quoted, one row per (identity, name-protection sequence). Fields
pack sub-fields with `$` and lists with `|`. Field order inside `postadress` is
street $ c/o $ city $ postcode $ country (Bolagsverket's docs list postcode before city; the data
does not).

Privacy: rows registered under a personal identity number (sole traders, estates) are dropped
here and never reach silver. Only organisation numbers are kept.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

EXPECTED_COLUMNS = [
    "organisationsidentitet", "namnskyddslopnummer", "registreringsland", "organisationsnamn",
    "organisationsform", "avregistreringsdatum", "avregistreringsorsak",
    "pagandeAvvecklingsEllerOmstruktureringsforfarande", "registreringsdatum",
    "verksamhetsbeskrivning", "postadress",
]
ORG_NR = "ORGNR-IDORG"
PRIMARY_NAME_TYPES = ("FORETAGSNAMN-ORGNAM", "NAMN-ORGNAM")


class ContractError(Exception):
    """The snapshot does not look like the file we were built for. Stop instead of loading it."""


def load_raw(con: duckdb.DuckDBPyConnection, txt: Path) -> None:
    con.execute(
        "create or replace temp table raw as select * from read_csv(?, delim=';', quote='\"', "
        "header=true, all_varchar=true)", [str(txt)])
    cols = [r[0] for r in con.execute("describe raw").fetchall()]
    if cols != EXPECTED_COLUMNS:
        raise ContractError(f"columns changed: expected {EXPECTED_COLUMNS}, got {cols}")


COMPANIES_SQL = f"""
create or replace temp table companies as
with base as (
    select
        split_part(organisationsidentitet, '$', 1) as org_nr,
        coalesce(try_cast(namnskyddslopnummer as integer), 0) as name_seq,
        list_filter(string_split(coalesce(organisationsnamn, ''), '|'), lambda x: x <> '') as names,
        organisationsform as legal_form,
        try_cast(registreringsdatum as date) as registered_on,
        try_cast(avregistreringsdatum as date) as deregistered_on,
        avregistreringsorsak as deregistration_reason,
        verksamhetsbeskrivning as description,
        string_split(coalesce(postadress, '$$$$'), '$') as addr
    from raw
    where split_part(organisationsidentitet, '$', 2) = '{ORG_NR}'
)
select
    org_nr, name_seq,
    split_part(coalesce(
        list_filter(names, lambda x: split_part(x, '$', 2) in {PRIMARY_NAME_TYPES})[1], names[1]), '$', 1) as name,
    legal_form, registered_on, deregistered_on, deregistration_reason, description,
    nullif(addr[1], '') as street, nullif(addr[2], '') as care_of, nullif(addr[3], '') as city,
    nullif(addr[4], '') as postcode
from base
"""

PROCEEDINGS_SQL = f"""
create or replace temp table proceedings as
select org_nr, name_seq, split_part(item, '$', 1) as code, try_cast(split_part(item, '$', 2) as date) as since
from (
    select
        split_part(organisationsidentitet, '$', 1) as org_nr,
        coalesce(try_cast(namnskyddslopnummer as integer), 0) as name_seq,
        unnest(list_filter(string_split(pagandeAvvecklingsEllerOmstruktureringsforfarande, '|'),
                           lambda x: x <> '')) as item
    from raw
    where split_part(organisationsidentitet, '$', 2) = '{ORG_NR}'
      and pagandeAvvecklingsEllerOmstruktureringsforfarande is not null
)
"""


def check(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Data-quality gate. Hard failures raise; the counts are returned for the run log."""
    dupes = con.execute("select count(*) from (select org_nr, name_seq from companies "
                        "group by all having count(*) > 1)").fetchone()[0]
    if dupes:
        raise ContractError(f"{dupes} duplicate (org_nr, name_seq) keys")
    bad_nr = con.execute("select count(*) from companies where not regexp_full_match(org_nr, '\\d{10}')"
                         ).fetchone()[0]
    if bad_nr:
        raise ContractError(f"{bad_nr} organisation numbers are not 10 digits")
    return {
        "raw_rows": con.execute("select count(*) from raw").fetchone()[0],
        "companies": con.execute("select count(*) from companies").fetchone()[0],
        "active": con.execute("select count(*) from companies where deregistered_on is null").fetchone()[0],
        "proceedings": con.execute("select count(*) from proceedings").fetchone()[0],
        "unparsed_dates": con.execute(
            "select count(*) from proceedings where since is null").fetchone()[0],
    }


def build_silver(txt: Path, out_dir: Path) -> dict[str, int]:
    """Parse one snapshot and write companies.parquet + proceedings.parquet into out_dir."""
    con = duckdb.connect()
    load_raw(con, txt)
    con.execute(COMPANIES_SQL)
    con.execute(PROCEEDINGS_SQL)
    stats = check(con)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in ("companies", "proceedings"):
        tmp = out_dir / f"{table}.parquet.tmp"
        con.execute(f"copy (select * from {table} order by all) to '{tmp}' (format parquet)")
        tmp.replace(out_dir / f"{table}.parquet")  # atomic: a crash never leaves half a table
    return stats
