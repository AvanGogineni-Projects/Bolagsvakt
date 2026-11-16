# 0002: Annual-report zips are not kept as bronze

Date: 2026-11-16 · Status: accepted

## Context

ADR 0001 keeps every raw file. For annual reports that means 137 GB for 2020–2026
(1,473 weekly parts), growing ~35 GB a year. The machine running the pipeline has 17 GB free.

## Decision

Each part is downloaded to a temp file, parsed, and only the Parquet output
(`facts`, `metrics`, `rejects`) is kept. The registry snapshot is still kept as bronze.

## Why this is safe

- Bolagsverket serves every part since 2020 at a stable URL, and parts are immutable once
  published. Reprocessing a part means downloading it again.
- The registry snapshot is different: it is overwritten weekly, so if we don't keep it, that week is gone for good.
- `facts.parquet` keeps every whole-company numeric fact, not just the metrics we use today, so a
  new metric can be added without re-downloading.

## When to revisit

When the pipeline moves to object storage (R2/S3 at a few dollars per 100 GB a month), or if
Bolagsverket stops serving old parts.
