"""Weekly registry run: download -> bronze -> silver -> history/events.

    python -m bolagsvakt.pipeline                      # fetch this week's file and apply it
    python -m bolagsvakt.pipeline --file x.zip --date 2026-11-16   # apply a file you already have

bronze/registry/<date>/bolagsverket_bulkfil.zip is written once and never overwritten; the
date is Bolagsverket's Last-Modified, so a rerun in the same week finds the same folder and
does nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

from bolagsvakt.history import apply_snapshot
from bolagsvakt.registry import build_silver

URL = "https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip"
DATA = Path(os.environ.get("BOLAGSVAKT_DATA", "data"))


def snapshot_date(last_modified: str) -> dt.date:
    return email.utils.parsedate_to_datetime(last_modified).date()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(bronze: Path, client: httpx.Client) -> tuple[Path, dt.date]:
    """Download the current snapshot into bronze unless that snapshot is already there."""
    day = snapshot_date(client.head(URL).raise_for_status().headers["last-modified"])
    dest = bronze / day.isoformat() / "bolagsverket_bulkfil.zip"
    if dest.exists():
        return dest, day
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with client.stream("GET", URL) as r, tmp.open("wb") as f:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            f.write(chunk)
    zipfile.ZipFile(tmp).testzip()  # a truncated download fails here, not three steps later
    tmp.replace(dest)
    return dest, day


def run(zip_path: Path, day: dt.date, data: Path = DATA) -> dict:
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            txt = Path(z.extract("bolagsverket_bulkfil.txt", tmp))
        silver_dir = data / "silver" / "registry" / day.isoformat()
        quality = build_silver(txt, silver_dir)
    events = apply_snapshot(silver_dir, day, data / "state" / "registry")
    report = {"snapshot": day.isoformat(), "sha256": sha256(zip_path), "quality": quality,
              "events": events, "seconds": round(time.time() - t0, 1)}
    (silver_dir / "run.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="use this zip instead of downloading")
    p.add_argument("--date", type=dt.date.fromisoformat, help="snapshot date for --file")
    a = p.parse_args(argv)
    bronze = DATA / "bronze" / "registry"
    if a.file:
        if not a.date:
            p.error("--file needs --date")
        dest = bronze / a.date.isoformat() / "bolagsverket_bulkfil.zip"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a.file, dest)
        zip_path, day = dest, a.date
    else:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            zip_path, day = fetch(bronze, client)
    print(json.dumps(run(zip_path, day), indent=2))


if __name__ == "__main__":
    main()
