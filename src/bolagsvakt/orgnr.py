"""Swedish organisation numbers as people type them -> the 10 digits we store."""
from __future__ import annotations

import re


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(digits):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def normalize(raw: str) -> str | None:
    """'556000-0001', '5560000001', '16556000-0001' -> '5560000001'; None if it can't be one.
    The last digit is a Luhn check digit, so most typos are caught here."""
    digits = re.sub(r"[\s-]", "", raw)
    if len(digits) == 12 and digits.startswith("16"):  # some systems prefix legal entities with 16
        digits = digits[2:]
    if not re.fullmatch(r"\d{10}", digits) or not luhn_ok(digits):
        return None
    return digits


def from_csv(text: str, limit: int) -> list[str]:
    """First cell of each line (',', ';' or tab separated). A header line is just an invalid entry."""
    out = []
    for line in text.splitlines():
        cell = re.split(r"[,;\t]", line, maxsplit=1)[0].strip().strip('"')
        if cell:
            out.append(cell)
        if len(out) > limit:
            raise ValueError(f"more than {limit} rows")
    return out
