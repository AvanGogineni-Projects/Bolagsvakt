# 0001: DuckDB + Parquet files, not a warehouse or Spark

Date: 2026-11-16 · Status: accepted

## Context

The weekly registry snapshot is ~1 GB of text (3M rows); annual reports add up to ~100 MB of
iXBRL per weekly part. The product has no revenue yet, so running cost matters.

## Decision

Bronze, silver and history are Parquet files; DuckDB does the parsing, diffing and SCD2 in SQL.
Postgres is added only for what the app serves (watchlists, users, the latest scores).

## Why

- A full weekly run takes 11 s on a laptop. Spark or a cloud warehouse would add cost and
  operations for no gain at this size.
- Parquet in folders maps one-to-one onto object storage (S3/R2) when it moves off the laptop,
  and stays readable by Spark/Snowflake/BigQuery if the data ever outgrows one machine.

## When to revisit

If a weekly run takes more than ~10 minutes, or several workers need to write concurrently.
