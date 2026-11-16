# Bolagsvakt: plan

## The product

Swedish SMEs sell on invoice to other companies and buy from suppliers they barely know. When a
customer goes bankrupt, the invoice is lost; when a supplier fails, deliveries stop. Credit
bureaus (UC, Creditsafe) cover this but are priced for banks and large firms.

**Bolagsvakt** watches a company's customers and suppliers for them:

1. Upload a list of organisation numbers (or connect the accounting system later).
2. Each week, Bolagsvakt checks every company against Bolagsverket's open data.
3. You get an alert when something changes that matters: bankruptcy or liquidation started,
   annual report late, auditor qualified the report, equity turned negative, revenue collapsed,
   board or address changed, company deregistered.
4. Each company has a risk score with the reasons behind it, not a black box.

Money: subscription per watched company (e.g. free up to 10, then tiers). Later: an API for
accounting/invoicing software, and the BRF (housing co-op) checker as a second product on the same data.

## Data sources (all free, no agreement, verified 2026-11-16)

| Source | What | Size / cadence |
|---|---|---|
| `bolagsverket_bulkfil.zip` | Every registered organisation: org number, names, legal form, registration and deregistration dates, deregistration reason, **ongoing bankruptcy/liquidation/reconstruction with start date**, postal address | 252 MB zip, weekly snapshot |
| `scb_bulkfil.zip` | SCB register: industry (SNI), size class, etc. | 71 MB zip, weekly |
| `arsredovisningar/<year>/<week>_<n>.zip` | Digitally filed annual reports (AB under K2/K3, ESEF), **iXBRL**, from 2020 | up to ~100 MB per part, weekly |
| `statistik/rakenskaps_forsening.csv`, `rev_forbehall.csv` | Late filings; auditor qualifications | small CSVs |

Source: [Bolagsverket – Nedladdningsbara filer](https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/nedladdningsbarafiler.2517.html)

Bolagsverket only publishes the **current** snapshot. History, and therefore every "what
changed" alert, exists only if we keep each weekly snapshot and diff them. That is the core
data-engineering problem.

## Architecture

```
 Bolagsverket / SCB (weekly)
        │  download, sha256, never overwrite
        ▼
 bronze: raw files, immutable, one folder per snapshot date
        │  parse + validate against a data contract (fail loudly on schema drift)
        ▼
 silver: typed Parquet per snapshot (companies, statuses, financial facts)
        │  diff against the previous snapshot
        ▼
 history: SCD2 company table (valid_from / valid_to) + company_events (append-only)
        │  dbt models: ratios, risk score with reasons
        ▼
 serving: Postgres ─► FastAPI ─► React app + weekly email digest
```

- **Orchestration:** Dagster, weekly partitions, backfills, asset checks that block bad data.
- **Transform:** DuckDB for the heavy local work, dbt for modelled tables and tests.
- **Serving:** Postgres (Supabase), FastAPI, React + TypeScript + Tailwind.
- **Privacy:** sole traders are registered under a personal identity number (personnummer).
  Those rows are excluded at the silver layer; we only store organisation numbers.

## Milestones

Each one is shippable and demoable on its own.

1. **Registry pipeline** (this week): download → bronze → parse with data contract → silver
   Parquet → SCD2 history → `company_events` (status, name, address, deregistration). Tests, CI.
2. **Annual reports:** stream weekly iXBRL zips, extract key facts (revenue, profit, equity,
   total assets, cash, employees) for K2/K3, store as facts per company and fiscal year.
   Backfill 2020→now.
3. **Risk signals:** ratios (equity ratio, cash, revenue trend), late filing, auditor
   qualification, negative equity, ongoing proceedings → risk score with reasons. Validate the
   score against companies that actually went bankrupt later (we have the labels in the data).
4. **App:** sign-in, organisations (multi-tenant), watchlist upload (CSV of org numbers),
   event feed, company page, weekly email digest. Deployed.
5. **Product:** landing page, Stripe billing, public API with keys and rate limits.

## Definition of done per milestone

Tests pass in CI, it runs end to end on real data, the README shows a real number from that
run, and an ADR records any decision someone could reasonably question.
