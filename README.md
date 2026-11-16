# Bolagsvakt

Weekly risk monitoring of Swedish companies from Bolagsverket's open data: upload the
organisation numbers of your customers and suppliers, get told when one of them starts going
wrong (bankruptcy, liquidation, late or qualified annual report, negative equity, deregistration).

Plan, data sources and milestones: [docs/PLAN.md](docs/PLAN.md). Decisions: [docs/adr/](docs/adr/).

## Status: milestone 1 (registry pipeline)

```
bolagsverket_bulkfil.zip (weekly, 252 MB)
  -> bronze/registry/<date>/   immutable, dated by Last-Modified, sha256 in the run report
  -> silver/registry/<date>/   companies.parquet, proceedings.parquet (data contract + quality gate)
  -> state/registry/           SCD2 history.parquet + append-only events.parquet
```

First real run, snapshot 2026-11-16:

| | |
|---|---|
| Rows in the file | 2,988,640 |
| Organisations kept (sole traders' personal ID numbers dropped) | 1,947,665 |
| Active | 914,055 |
| Ongoing proceedings (liquidation, bankruptcy, merger, reconstruction) | 98,224 |
| Full parse + quality gate + history | 11 s on a laptop |
| Weekly diff against the previous snapshot | 4.7 s, 0 false changes when nothing changed |

What makes it hold up:

- **Data contract:** the header must match exactly; a renamed column stops the load instead of
  silently loading nulls. Keys must be unique and org numbers 10 digits.
- **Idempotent and ordered:** rerunning a week is a no-op; applying an older week after a newer one is refused.
- **Atomic writes:** every Parquet file is written to a temp file and renamed, and the state
  marker is written last, so a crash mid-run is fixed by rerunning.
- **Privacy by design:** rows registered under a personnummer never leave the parse step.

## Status: milestone 2 (annual reports)

```
arsredovisningar/<year>/<week>_<part>.zip (1,473 parts since 2020, 137 GB)
  -> per filing: pick the annual report (not the auditor's report) and parse its iXBRL
  -> silver/annual_reports/<part>/   facts.parquet (every whole-company number),
                                     metrics.parquet (key metrics, this year + prior year),
                                     rejects.parquet (filings that failed, with the reason)
```

First real run, the 4 newest weekly parts (week 46, 2026):

| | |
|---|---|
| Annual reports parsed | 4,024, 0 rejected |
| Matched to a company in the registry | 100% |
| With a prior year in the same report | 3,672 |
| Coverage: equity, total assets / cash / revenue / employees | 100% / 98% / 93% / 59% |
| Negative equity · equity below half the share capital (legal solvency trigger) | 139 · 214 |
| Balance sheets that don't balance in the filing itself | 3 |
| Speed | ~17 s per 100 MB part, output 2.8 MB |

What makes it hold up:

- **Number formats done properly:** Swedish formats (`1 234,5`), `scale`, `sign`, and dimension
  contexts (per-segment figures are not mistaken for company totals).
- **Duplicates resolved, not hidden:** when a filing tags the same number twice, the most precise
  wins and any disagreement is counted per report.
- **One bad filing never drops a week:** it goes to `rejects` with the reason. A dropped
  download is retried with backoff, and a part that still fails is left for the next run.
- **Raw zips not kept:** [ADR 0002](docs/adr/0002-annual-reports-not-kept-as-bronze.md) explains why.

## Status: milestone 3 (risk score)

Each company gets 14 yes/no warning signs an accountant would recognise (negative equity, equity
below half the share capital, annual report filed after the 7-month legal deadline, cash under
10% of short-term debts, losses, falling revenue...). A logistic regression learns how much each
sign matters from what actually happened to companies after they filed. A company's reasons are
its active signs, strongest first. The weights live in [`models/risk_v1.json`](models/risk_v1.json),
so every score can be traced.

**Validation, out of time:** trained on reports filed in 2024 weeks 1–26 and tested on weeks
27–52 (149,572 reports, 4,398 later bankruptcies). Outcomes come from the registry: a bankruptcy
started or concluded after the report was filed.

| | Model | "Negative equity" rule alone |
|---|---|---|
| AUC | **0.784** | 0.609 |
| Share of bankruptcies in the riskiest 10% | **41%** | 28% |
| Riskiest 1% that actually went bankrupt | **23.6%** (8× the 2.9% average) | 8.4% |

Strongest signs: late filing, negative equity, low cash.

**Scoring:** after backfilling every report filed in 2024–2026 (883 weekly parts, 1,253,798
reports, 167 rejected filings), 508,205 active companies are scored on their latest report,
93% of them on a 2025 or 2026 report (`gold/risk_scores.parquet`). 9,725 are already in
bankruptcy, liquidation or reconstruction, and that is their first reason. 24,135 more score 5×
the average or higher.

Known limits:
- The label is a bankruptcy recorded *after* filing. A finished bankruptcy only keeps its
  deregistration date, so its start date is approximated by the filing order.

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m bolagsvakt.pipeline          # download this week's snapshot and apply it
.venv/bin/python -m bolagsvakt.annual_reports --year 2024 --workers 4   # or --latest 4, or --list
.venv/bin/python -m bolagsvakt.risk train         # -> models/risk_v1.json with its validation
.venv/bin/python -m bolagsvakt.risk score         # -> data/gold/risk_scores.parquet
.venv/bin/ruff check src tests && .venv/bin/pytest -q
```
