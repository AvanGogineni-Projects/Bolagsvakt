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

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m bolagsvakt.pipeline          # download this week's snapshot and apply it
.venv/bin/python -m bolagsvakt.annual_reports --latest 4   # or --year 2025, or --list
.venv/bin/ruff check src tests && .venv/bin/pytest -q
```
