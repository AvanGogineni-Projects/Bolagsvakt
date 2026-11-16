"""Bolagsverket's weekly annual-report bundles -> financial facts and key metrics.

Layout: arsredovisningar/<year>/<week>_<part>.zip holds one zip per filing named
<org_nr>_<fiscal_year_end>.zip, which holds the annual report (iXBRL) and, for audited companies,
a second iXBRL document with the auditor's report.

    python -m bolagsvakt.annual_reports --list                 # how many parts exist, total size
    python -m bolagsvakt.annual_reports --latest 4             # ingest the 4 newest parts
    python -m bolagsvakt.annual_reports --year 2025            # backfill a whole year

Each part is one unit: downloaded to a temp file, parsed, and written as
silver/annual_reports/<part>/{facts,metrics,rejects}.parquet in one atomic rename. A part whose
silver folder exists is skipped, so reruns resume.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from bolagsvakt.ixbrl import NotIXBRL, parse

BASE = "https://vardefulla-datamangder.bolagsverket.se/arsredovisningar-bulkfiler"
DATA = Path(os.environ.get("BOLAGSVAKT_DATA", "data"))
FILING = re.compile(r"(\d{10})_(\d{4}-\d{2}-\d{2})\.zip$")
P = "se-gen-base:"
# metric -> concepts in order of preference (first one present wins)
METRICS = {
    "revenue": [P + "Nettoomsattning"],
    "operating_profit": [P + "Rorelseresultat"],
    "profit_after_financial_items": [P + "ResultatEfterFinansiellaPoster"],
    "net_profit": [P + "AretsResultat"],
    "total_assets": [P + "Tillgangar"],
    "equity": [P + "EgetKapital"],
    "equity_and_liabilities": [P + "EgetKapitalSkulder"],
    "share_capital": [P + "Aktiekapital"],
    "untaxed_reserves": [P + "ObeskattadeReserver"],
    "cash": [P + "KassaBank", P + "KassaBankExklRedovisningsmedel"],
    "current_assets": [P + "Omsattningstillgangar"],
    "current_liabilities": [P + "KortfristigaSkulder"],
    "long_term_liabilities": [P + "LangfristigaSkulder"],
    "employees": [P + "MedelantaletAnstallda"],
}


def list_parts(client: httpx.Client) -> list[tuple[str, int]]:
    """(key, size) of every weekly part, following the S3-style listing's pagination."""
    out, marker = [], None
    while True:
        params = {"prefix": "arsredovisningar/", "delimiter": "\\"} | ({"marker": marker} if marker else {})
        xml = retry(lambda p=params: client.get(BASE, params=p).raise_for_status().text)
        out += [(k, int(s)) for k, s in zip(re.findall(r"<Key>([^<]+)</Key>", xml),
                                               re.findall(r"<Size>(\d+)</Size>", xml))]
        nxt = re.findall(r"<NextMarker>([^<]+)</NextMarker>", xml)
        if "<IsTruncated>true" not in xml or not nxt:
            return [(k, s) for k, s in out if k.endswith(".zip")]
        marker = nxt[0]


def _pick_report(inner: zipfile.ZipFile) -> tuple[list, list[str], bool]:
    """Parse every document in a filing; the one with the most numeric facts is the annual report."""
    parsed = []
    for name in inner.namelist():
        if name.lower().endswith((".xhtml", ".html", ".htm")):
            try:
                parsed.append(parse(inner.read(name)))
            except NotIXBRL:
                continue
    if not parsed:
        raise NotIXBRL("no parseable iXBRL document")
    parsed.sort(key=lambda p: len(p[0]), reverse=True)
    facts, warnings = parsed[0]
    return facts, warnings, len(parsed) > 1


def metrics_for(facts: list, fiscal_end: str) -> dict[str, dict]:
    """Key metrics for the reported year and the prior year the same report also shows."""
    # The prior year is the latest income-statement period ending before this one. A first-year
    # company has none; its only earlier date is the opening balance, which is not a prior year.
    prior_ends = [f.end for f in facts if f.start is not None and f.end < fiscal_end]
    periods = {"current": fiscal_end, "prior": max(prior_ends, default=None)}
    out = {}
    for period, end in periods.items():
        if end is None:
            continue
        by_concept = {f.concept: f.value for f in facts if f.end == end}
        row = {m: next((float(by_concept[c]) for c in cs if c in by_concept), None) for m, cs in METRICS.items()}
        if any(v is not None for v in row.values()):
            out[period] = {"period_end": end, **row}
    return out


def process_part(zip_path: Path, part: str) -> dict[str, list[dict]]:
    facts_rows, metric_rows, rejects = [], [], []
    with zipfile.ZipFile(zip_path) as outer:
        for name in outer.namelist():
            m = FILING.search(name)
            if not m:
                rejects.append({"part": part, "file": name, "error": "unexpected file name"})
                continue
            org_nr, fiscal_end = m.groups()
            try:
                facts, warnings, audited = _pick_report(zipfile.ZipFile(io.BytesIO(outer.read(name))))
            except (NotIXBRL, ValueError, zipfile.BadZipFile) as e:  # one bad filing must not drop the part
                rejects.append({"part": part, "file": name, "error": f"{type(e).__name__}: {e}"[:300]})
                continue
            facts_rows += [{"org_nr": org_nr, "fiscal_end": fiscal_end, "concept": f.concept,
                            "period_start": f.start, "period_end": f.end, "value": float(f.value),
                            "unit": f.unit} for f in facts]
            for period, row in metrics_for(facts, fiscal_end).items():
                metric_rows.append({"org_nr": org_nr, "fiscal_end": fiscal_end, "period": period,
                                    "part": part, "has_audit_report": audited,
                                    "duplicate_conflicts": len(warnings), **row})
    return {"facts": facts_rows, "metrics": metric_rows, "rejects": rejects}


SCHEMAS = {
    "facts": pa.schema([("org_nr", pa.string()), ("fiscal_end", pa.string()), ("concept", pa.string()),
                        ("period_start", pa.string()), ("period_end", pa.string()), ("value", pa.float64()),
                        ("unit", pa.string())]),
    "metrics": pa.schema([("org_nr", pa.string()), ("fiscal_end", pa.string()), ("period", pa.string()),
                          ("part", pa.string()), ("has_audit_report", pa.bool_()),
                          ("duplicate_conflicts", pa.int32()), ("period_end", pa.string()),
                          *[(m, pa.float64()) for m in METRICS]]),
    "rejects": pa.schema([("part", pa.string()), ("file", pa.string()), ("error", pa.string())]),
}


def write_part(tables: dict[str, list[dict]], out_dir: Path) -> None:
    """All three tables land in a temp folder that is renamed into place: a part is all or nothing."""
    tmp = out_dir.with_name(out_dir.name + ".tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMAS[name]), tmp / f"{name}.parquet")
    tmp.rename(out_dir)


def retry(call, *, retries: int = 4, sleep=time.sleep):
    """Run call() again with backoff on transport errors and 5xx (the server drops long downloads
    and answers 503 under load now and then); 4xx fails at once."""
    for attempt in range(retries + 1):
        try:
            return call()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                raise
            if attempt == retries:
                raise
            sleep(min(10 * 2**attempt, 300))


def download(client: httpx.Client, url: str, dest, *, sleep=time.sleep) -> None:
    """Stream url into the open file dest; a retry starts the file over."""
    def attempt():
        dest.seek(0)
        dest.truncate()
        with client.stream("GET", url) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                dest.write(chunk)
        dest.flush()
    retry(attempt, sleep=sleep)


def ingest_one(key: str, data: Path = DATA) -> str | None:
    """Ingest one part unless it is done. Returns the part name if it failed (left for the next run)."""
    part = key.removeprefix("arsredovisningar/").removesuffix(".zip").replace("/", "_")
    out_dir = data / "silver" / "annual_reports" / part
    if out_dir.exists():
        return None
    # Not kept as bronze: 137 GB for 2020-2026, and Bolagsverket serves every part
    # permanently, so a part can be re-fetched to reprocess it (ADR 0002).
    t0 = time.time()
    with httpx.Client(timeout=600, follow_redirects=True) as client, \
            tempfile.NamedTemporaryFile(suffix=".zip") as f:
        try:
            download(client, f"{BASE}/{key}", f)
        except httpx.HTTPError as e:
            print(f"{part}: FAILED {type(e).__name__}, will retry on the next run", flush=True)
            return part
        tables = process_part(Path(f.name), part)
    write_part(tables, out_dir)
    print(f"{part}: {len({(r['org_nr'], r['fiscal_end']) for r in tables['metrics']})} reports, "
          f"{len(tables['facts'])} facts, {len(tables['rejects'])} rejects, {time.time() - t0:.1f}s", flush=True)
    return None


def ingest(keys: list[str], workers: int = 1) -> list[str]:
    """Ingest parts that are not done yet, `workers` parts at a time (each part is independent and
    written by exactly one process). Returns the parts that failed."""
    if workers == 1:
        results = [ingest_one(k) for k in keys]
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(workers) as pool:
            results = list(pool.map(ingest_one, keys))
    return [r for r in results if r]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--latest", type=int)
    g.add_argument("--year", type=int)
    p.add_argument("--workers", type=int, default=1, help="parts processed in parallel (be kind: <= 4)")
    a = p.parse_args(argv)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        parts = list_parts(client)
    parts.sort(key=lambda kv: tuple(int(x) for x in re.findall(r"\d+", kv[0])))  # (year, week, part)
    if a.list:
        years = {}
        for k, s in parts:
            y = k.split("/")[1]
            years[y] = (years.get(y, (0, 0))[0] + 1, years.get(y, (0, 0))[1] + s)
        for y, (n, s) in sorted(years.items()):
            print(f"{y}: {n} parts, {s / 1e9:.1f} GB")
        return
    keys = [k for k, _ in parts]
    failed = ingest(keys[-a.latest:] if a.latest else [k for k in keys if k.split("/")[1] == str(a.year)],
                    a.workers)
    if failed:
        print(f"{len(failed)} parts failed; rerun the same command to retry them: {failed}")


if __name__ == "__main__":
    main()
