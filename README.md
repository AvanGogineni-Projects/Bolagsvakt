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

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m bolagsvakt.pipeline          # download this week's snapshot and apply it
.venv/bin/ruff check src tests && .venv/bin/pytest -q
```
