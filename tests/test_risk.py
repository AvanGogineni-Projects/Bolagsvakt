import datetime as dt

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from bolagsvakt.annual_reports import METRICS, SCHEMAS
from bolagsvakt.risk import SIGNALS, features_sql, labelled, probability, reasons


def metric_row(org, period, part="2024_07_3", fiscal_end="2023-06-30", **values):
    row = {"org_nr": org, "fiscal_end": fiscal_end, "period": period, "part": part, "has_audit_report": False,
           "duplicate_conflicts": 0, "period_end": fiscal_end, **{m: None for m in METRICS}}
    row.update(values)
    return row


HEALTHY = {"equity": 500_000.0, "share_capital": 25_000.0, "total_assets": 1_000_000.0, "equity_and_liabilities": 1_000_000.0,
               "net_profit": 50_000.0, "revenue": 2_000_000.0, "cash": 300_000.0, "current_assets": 600_000.0,
               "current_liabilities": 200_000.0}


@pytest.fixture
def metrics(tmp_path):
    rows = [
        # healthy, filed on time (FY ends 2023-12-31, filed week 7 of 2024), with a prior year
        metric_row("5560000001", "current", fiscal_end="2023-12-31", **HEALTHY),
        metric_row("5560000001", "prior", fiscal_end="2023-12-31", **HEALTHY),
        # distressed: negative equity, losses two years, revenue collapse, no cash, filed late
        metric_row("5560000002", "current", **(HEALTHY | {"equity": -10_000.0, "net_profit": -90_000.0,
                                                               "revenue": 500_000.0, "cash": 1_000.0})),
        metric_row("5560000002", "prior", **(HEALTHY | {"net_profit": -20_000.0})),
        # first report, refiled: appears in two parts, the earlier filing counts
        metric_row("5560000003", "current", part="2024_09_1", fiscal_end="2023-12-31", **HEALTHY),
        metric_row("5560000003", "current", part="2024_08_2", fiscal_end="2023-12-31", **HEALTHY),
    ]
    path = tmp_path / "metrics.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMAS["metrics"]), path)
    return str(path)


def flags(metrics):
    rel = duckdb.sql(features_sql(metrics))
    return {r[0]: dict(zip(rel.columns, r)) for r in rel.fetchall()}


def test_healthy_company_raises_no_signals(metrics):
    f = flags(metrics)["5560000001"]
    assert f["filed_on"] == dt.date(2024, 2, 18)
    assert [s for s in SIGNALS if f[s]] == []


def test_distressed_company_signals(metrics):
    f = flags(metrics)["5560000002"]
    assert {s for s in SIGNALS if f[s]} == {"negative_equity", "loss", "loss_two_years", "revenue_drop",
                                            "equity_halved", "low_cash", "late_filing"}


def test_refiled_report_counts_once_from_its_first_filing(metrics):
    f = flags(metrics)
    assert len(f) == 3
    assert (f["5560000003"]["part"], f["5560000003"]["first_report"]) == ("2024_08_2", 1)


def test_labels_only_count_bankruptcy_after_filing(metrics, tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    duckdb.sql("select * from (values ('5560000002', 0, 'KK-AVOMFO', date '2025-03-01'),"
               "('5560000003', 0, 'KK-AVOMFO', date '2024-01-15')) t(org_nr, name_seq, code, since)"
               ).write_parquet(str(reg / "proceedings.parquet"))
    duckdb.sql("select * from (values ('5560000001', 'KKAV-AVORG', date '2025-06-01')) "
               "t(org_nr, deregistration_reason, deregistered_on)").write_parquet(str(reg / "companies.parquet"))
    con = duckdb.connect()
    labelled(con, metrics, reg)
    got = dict(con.execute("select org_nr, went_bankrupt from ds").fetchall())
    # 1: deregistered after a bankruptcy that ended after filing; 2: bankruptcy started after filing;
    # 3: already bankrupt before filing -> dropped, nothing left to predict
    assert got == {"5560000001": 1, "5560000002": 1}


def test_reasons_are_active_risk_raising_signs_strongest_first():
    model = {"intercept": -4.0, "weights": {"negative_equity": 1.5, "late_filing": 2.0, "loss": 0.3,
                                            "first_report": -0.5}}
    active = {"negative_equity": 1, "late_filing": 1, "first_report": 1, "loss": 0}
    assert reasons(model, active) == [SIGNALS["late_filing"][1], SIGNALS["negative_equity"][1]]
    assert probability(model, {}) == pytest.approx(1 / (1 + 2.718281828 ** 4), rel=1e-6)
