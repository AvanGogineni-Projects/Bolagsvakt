"""Bankruptcy risk from annual reports: explainable warning signs, weighted by real outcomes.

    python -m bolagsvakt.risk train      # fit on 2024 filings, validate on later ones -> models/risk_v1.json
    python -m bolagsvakt.risk score      # score every active company's latest report -> gold/risk_scores.parquet

Each company gets yes/no warning signs an accountant would recognise. A logistic regression learns
how much each sign raises the odds of bankruptcy, from what actually happened to companies after
they filed. A company's reasons are its active signs, strongest first, so the score is never a
black box. The model file is small JSON in git: every score can be traced to the exact weights.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import duckdb

DATA = Path(os.environ.get("BOLAGSVAKT_DATA", "data"))
MODEL = Path(__file__).resolve().parents[2] / "models" / "risk_v1.json"

# name -> (SQL over c = this year, p = prior year, r = report; plain-language reason)
SIGNALS = {
    "negative_equity": ("c.equity < 0", "Equity is negative: debts exceed assets"),
    "below_half_share_capital": (
        "c.equity >= 0 and c.share_capital > 0 and c.equity < c.share_capital / 2",
        "Equity is below half the share capital, the legal trigger for a solvency check"),
    "low_equity_ratio": ("c.equity >= 0 and c.total_assets > 0 and c.equity / c.total_assets < 0.1",
                         "Less than 10% of assets are financed by equity"),
    "loss": ("c.net_profit < 0", "Made a loss this year"),
    "loss_two_years": ("c.net_profit < 0 and p.net_profit < 0", "Made a loss two years in a row"),
    "revenue_drop": ("p.revenue > 0 and coalesce(c.revenue, 0) < 0.7 * p.revenue",
                     "Revenue fell by more than 30%"),
    "equity_halved": ("p.equity > 0 and c.equity < 0.5 * p.equity", "Equity more than halved in a year"),
    "low_cash": ("c.current_liabilities > 0 and coalesce(c.cash, 0) < 0.1 * c.current_liabilities",
                 "Cash covers less than 10% of short-term debts"),
    "current_ratio_below_1": ("c.current_liabilities > 0 and coalesce(c.current_assets, 0) < c.current_liabilities",
                              "Short-term assets don't cover short-term debts"),
    "books_dont_balance": ("abs(c.total_assets - c.equity_and_liabilities) > 1",
                           "The filed balance sheet doesn't balance"),
    "late_filing": ("r.filed_on > c.fiscal_end + interval 7 month",
                    "Annual report filed after the 7-month legal deadline"),
    "first_report": ("p.org_nr is null", "First annual report: no track record yet"),
    "no_revenue": ("coalesce(c.revenue, 0) = 0", "No revenue"),
    "small_balance_sheet": ("c.total_assets < 100000", "Total assets under 100,000 SEK"),
}
ACTIVE_PROCEEDINGS = {
    "KK-AVOMFO": "In bankruptcy",
    "LI-AVOMFO": "In liquidation",
    "FR-AVOMFO": "In company reconstruction",
}


def features_sql(metrics: str) -> str:
    """One row per filed report with its signals as 0/1 columns. filed_on is the Sunday of the
    ISO week whose bundle carried the report ('2024_07_3' -> 2024-02-18)."""
    signals = ",\n".join(f"coalesce(({sql}), false)::int as {name}" for name, (sql, _) in SIGNALS.items())
    return f"""
    with m as (select * replace (cast(fiscal_end as date) as fiscal_end) from read_parquet('{metrics}')),
    first_filing as (  -- a refiled report appears in several parts; the first filing counts
        select org_nr, fiscal_end, min(part) as part from m where period = 'current' group by all),
    r as (select *, cast(date_trunc('week', make_date(cast(split_part(part, '_', 1) as int), 1, 4))
                         + to_weeks(cast(split_part(part, '_', 2) as int) - 1) + interval 6 day as date) as filed_on
          from first_filing)
    select c.org_nr, c.fiscal_end, r.filed_on, r.part,
           {signals}
    from r
    join m c on c.org_nr = r.org_nr and c.fiscal_end = r.fiscal_end and c.part = r.part and c.period = 'current'
    left join m p on p.org_nr = r.org_nr and p.fiscal_end = r.fiscal_end and p.part = r.part and p.period = 'prior'
    """


def labelled(con: duckdb.DuckDBPyConnection, metrics: str, registry: Path) -> None:
    """Table `ds`: features + went_bankrupt (a bankruptcy recorded after filing, by the snapshot).
    Reports filed while the company was already bankrupt are dropped (nothing left to predict)."""
    con.execute(f"create or replace temp table f as {features_sql(metrics)}")
    con.execute(f"""create or replace temp table ds as
        select f.*, (exists (select 1 from '{registry}/proceedings.parquet' p
                              where p.org_nr = f.org_nr and p.code = 'KK-AVOMFO' and p.since >= f.filed_on)
                     or exists (select 1 from '{registry}/companies.parquet' c
                                where c.org_nr = f.org_nr and c.deregistration_reason = 'KKAV-AVORG'
                                  and c.deregistered_on >= f.filed_on))::int as went_bankrupt
        from f
        where not exists (select 1 from '{registry}/proceedings.parquet' p
                          where p.org_nr = f.org_nr and p.code = 'KK-AVOMFO' and p.since < f.filed_on)""")


def probability(model: dict, active: dict[str, int]) -> float:
    z = model["intercept"] + sum(model["weights"][s] * active.get(s, 0) for s in model["weights"])
    return 1 / (1 + math.exp(-z))


def reasons(model: dict, active: dict[str, int]) -> list[str]:
    """Active signs that raise the risk, strongest first, in plain language."""
    on = [s for s in model["weights"] if active.get(s) and model["weights"][s] > 0]
    return [SIGNALS[s][1] for s in sorted(on, key=lambda s: -model["weights"][s])]


def evaluate(y, p) -> dict:
    from sklearn.metrics import roc_auc_score
    order = sorted(range(len(p)), key=lambda i: -p[i])
    positives = sum(y)
    top10 = order[: len(order) // 10]
    top1 = order[: len(order) // 100]
    return {"reports": len(y), "bankruptcies": int(positives), "base_rate": round(positives / len(y), 4),
            "auc": round(roc_auc_score(y, p), 3),
            "top10pct_captures": round(sum(y[i] for i in top10) / positives, 3),
            "top1pct_precision": round(sum(y[i] for i in top1) / len(top1), 3)}


def train(metrics: str, registry: Path, split_week: int = 27) -> dict:
    """Fit on reports filed in 2024 weeks 1..split_week-1, validate on the rest of 2024."""
    from sklearn.linear_model import LogisticRegression
    con = duckdb.connect()
    labelled(con, metrics, registry)
    names = list(SIGNALS)
    rows = con.execute(f"select part, {', '.join(names)}, went_bankrupt from ds "
                       "where part like '2024_%' order by org_nr, fiscal_end").fetchall()
    week = lambda part: int(part.split("_")[1])
    tr = [r for r in rows if week(r[0]) < split_week]
    te = [r for r in rows if week(r[0]) >= split_week]
    xs = lambda rs: [list(r[1:-1]) for r in rs]
    ys = lambda rs: [r[-1] for r in rs]
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(xs(tr), ys(tr))
    model = {"version": "risk_v1", "trained_on": f"2024 filings, weeks 1-{split_week - 1}",
             "label": "bankruptcy recorded after filing, by the registry snapshot",
             "intercept": float(lr.intercept_[0]),
             "weights": {n: round(float(w), 4) for n, w in zip(names, lr.coef_[0])}}
    p_te = [probability(model, dict(zip(names, x))) for x in xs(te)]
    neg_eq = [x[names.index("negative_equity")] for x in xs(te)]
    model["validation"] = {"on": f"2024 filings, weeks {split_week}-52", **evaluate(ys(te), p_te),
                           "baseline_negative_equity_only": evaluate(ys(te), [float(v) for v in neg_eq])}
    model["base_rate_train"] = round(sum(ys(tr)) / len(tr), 4)
    return model


def score(metrics: str, registry: Path, model: dict, out: Path) -> dict:
    """Latest report of every active company -> probability, risk vs average, reasons."""
    con = duckdb.connect()
    con.execute(f"create temp table f as {features_sql(metrics)}")
    con.execute("create temp table latest as select * from f qualify row_number() over "
                "(partition by org_nr order by fiscal_end desc, filed_on desc) = 1")
    rows = con.execute(f"""
        select l.*, c.name, (select list(p.code) from '{registry}/proceedings.parquet' p
                             where p.org_nr = l.org_nr) as procs
        from latest l
        join '{registry}/companies.parquet' c on c.org_nr = l.org_nr and c.deregistered_on is null""")
    cols = [d[0] for d in rows.description]
    base = model["base_rate_train"]
    out_rows = []
    for row in rows.fetchall():
        r = dict(zip(cols, row))
        active = {s: r[s] for s in SIGNALS}
        p = probability(model, active)
        why = [ACTIVE_PROCEEDINGS[c] for c in (r["procs"] or []) if c in ACTIVE_PROCEEDINGS] + reasons(model, active)
        out_rows.append({"org_nr": r["org_nr"], "name": r["name"], "fiscal_end": r["fiscal_end"],
                         "filed_on": r["filed_on"], "probability": round(p, 4),
                         "times_average": round(p / base, 1), "reasons": why,
                         "in_proceedings": any(c in ACTIVE_PROCEEDINGS for c in (r["procs"] or []))})
    import pyarrow as pa
    import pyarrow.parquet as pq
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(out_rows), tmp)
    tmp.replace(out)
    return {"companies_scored": len(out_rows)}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["train", "score"])
    p.add_argument("--registry", type=Path, help="silver registry snapshot folder (default: latest)")
    a = p.parse_args(argv)
    registry = a.registry or max((DATA / "silver" / "registry").iterdir())
    metrics = str(DATA / "silver" / "annual_reports" / "*" / "metrics.parquet")
    if a.command == "train":
        model = train(metrics, registry)
        MODEL.parent.mkdir(exist_ok=True)
        MODEL.write_text(json.dumps(model, indent=2) + "\n")
        print(json.dumps(model, indent=2))
    else:
        print(score(metrics, registry, json.loads(MODEL.read_text()), DATA / "gold" / "risk_scores.parquet"))


if __name__ == "__main__":
    main()
