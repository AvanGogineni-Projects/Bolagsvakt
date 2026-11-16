import datetime as dt
from pathlib import Path

import duckdb
import pytest

from bolagsvakt.history import OutOfOrder, apply_snapshot
from bolagsvakt.registry import build_silver

FIXTURE = Path(__file__).parent / "fixtures" / "registry_sample.txt"
W1, W2 = dt.date(2026, 11, 16), dt.date(2026, 11, 23)


def snapshot(tmp_path, name, text):
    src = tmp_path / f"{name}.txt"
    src.write_text(text)
    build_silver(src, tmp_path / name)
    return tmp_path / name


def week2_text():
    t = FIXTURE.read_text()
    t = t.replace('"Alfa AB$FORETAGSNAMN', '"Alfa Group AB$FORETAGSNAMN')               # renamed
    t = t.replace('"";"";"|KK-AVOMFO$2026-10-01"', '"2026-11-20";"KKAV-AVORG";""')       # bankruptcy done
    t = t.replace('"LI-AVOMFO$2026-09-01|FR-AVOMFO$2026-09-15"', '"LI-AVOMFO$2026-09-01"')  # reconstruction over
    return t + ('"5560000009$ORGNR-IDORG";"";"SE-LAND";"Nya AB$FORETAGSNAMN-ORGNAM$2026-11-18";"AB-ORGFO";"";"";'
                '"KK-AVOMFO$2026-11-21";"2026-11-18";"Ny.";"Gatan 5$$LUND$22100$SE-LAND"\n')


@pytest.fixture
def state(tmp_path):
    first = snapshot(tmp_path, "w1", FIXTURE.read_text())
    assert apply_snapshot(first, W1, tmp_path / "state") == {"versions": 4}  # baseline: no events
    second = snapshot(tmp_path, "w2", week2_text())
    return tmp_path / "state", apply_snapshot(second, W2, tmp_path / "state"), second


def events(state_dir):
    return duckdb.connect().execute(
        f"select org_nr, event, detail from '{state_dir}/events.parquet' order by all").fetchall()


def test_diff_emits_one_event_per_real_change(state):
    state_dir, _, _ = state
    assert events(state_dir) == [
        ("5560000001", "name_changed", "Alfa AB -> Alfa Group AB"),
        ("5560000002", "deregistered", "2026-11-20 KKAV-AVORG"),
        ("5560000002", "proceeding_ended", "KK-AVOMFO"),
        ("5560000004", "proceeding_ended", "FR-AVOMFO"),
        ("5560000009", "proceeding_started", "KK-AVOMFO 2026-11-21"),
        ("5560000009", "registered", "Nya AB"),
    ]


def test_scd2_keeps_old_version_closed_and_one_open_per_company(state):
    state_dir, stats, _ = state
    con = duckdb.connect()
    h = f"'{state_dir}/history.parquet'"
    assert stats["versions"] == 7  # 4 baseline + 2 changed + 1 new
    assert con.execute(f"select name, valid_from, valid_to from {h} where org_nr = '5560000001' "
                       "order by valid_from").fetchall() == [("Alfa AB", W1, W2), ("Alfa Group AB", W2, None)]
    assert con.execute(f"select count(*) from (select org_nr from {h} where valid_to is null "
                       "group by org_nr having count(*) > 1)").fetchone()[0] == 0


def test_rerun_is_a_noop_and_older_snapshot_is_refused(state):
    state_dir, _, second = state
    before = events(state_dir)
    assert apply_snapshot(second, W2, state_dir) == {"skipped": 1}
    assert events(state_dir) == before
    with pytest.raises(OutOfOrder):
        apply_snapshot(second, W1, state_dir)
