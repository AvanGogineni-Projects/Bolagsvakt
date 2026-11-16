from pathlib import Path

import duckdb
import pytest

from bolagsvakt.registry import ContractError, build_silver

FIXTURE = Path(__file__).parent / "fixtures" / "registry_sample.txt"


@pytest.fixture
def silver(tmp_path):
    stats = build_silver(FIXTURE, tmp_path)
    con = duckdb.connect()
    companies = {r[0]: r for r in con.execute(
        f"select org_nr, name, city, postcode, care_of, deregistered_on, description "
        f"from '{tmp_path}/companies.parquet'").fetchall()}
    procs = con.execute(f"select org_nr, code, since from '{tmp_path}/proceedings.parquet' order by all").fetchall()
    return stats, companies, procs


def test_personal_identity_numbers_never_reach_silver(silver):
    stats, companies, _ = silver
    assert stats["raw_rows"] == 5
    assert set(companies) == {"5560000001", "5560000002", "5560000003", "5560000004"}


def test_primary_name_address_order_and_free_text(silver):
    _, c, _ = silver
    assert c["5560000001"][1:5] == ("Alfa AB", "STOCKHOLM", "11122", "c/o Berg")
    assert c["5560000001"][6] == "Konsultverksamhet; IT och data."  # ';' inside quotes survives
    assert c["5560000003"][2] is None and str(c["5560000003"][5]) == "2020-06-30"


def test_proceedings_split_and_leading_pipe(silver):
    _, _, procs = silver
    assert [(o, code, str(d)) for o, code, d in procs] == [
        ("5560000002", "KK-AVOMFO", "2026-10-01"),
        ("5560000004", "FR-AVOMFO", "2026-09-15"),
        ("5560000004", "LI-AVOMFO", "2026-09-01"),
    ]


def test_schema_drift_stops_the_load(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(FIXTURE.read_text().replace("postadress", "adress", 1))
    with pytest.raises(ContractError, match="columns changed"):
        build_silver(bad, tmp_path / "out")


def test_snapshot_date_comes_from_last_modified():
    import datetime as dt

    from bolagsvakt.pipeline import snapshot_date
    assert snapshot_date("Mon, 16 Nov 2026 02:34:26 GMT") == dt.date(2026, 11, 16)
