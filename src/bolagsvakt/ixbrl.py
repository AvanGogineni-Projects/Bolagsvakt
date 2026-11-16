"""Inline XBRL (iXBRL) annual report -> numeric facts.

A Swedish digital annual report is an XHTML page with numbers tagged like
    <ix:nonFraction name="se-gen-base:Nettoomsattning" contextRef="period0" scale="3"
                    format="ixt:numspacecomma" sign="-">750</ix:nonFraction>
value = parsed text * 10**scale, negated if sign="-". The context says which period the
number belongs to (a duration for the income statement, an instant for the balance sheet).
The same fact is often tagged twice (e.g. in thousands in the summary, exact in the statement);
the most precise one wins and a disagreement between them is reported, not hidden.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

NS = {"ix": "http://www.xbrl.org/2013/inlineXBRL", "xbrli": "http://www.xbrl.org/2003/instance"}
IX = f"{{{NS['ix']}}}"


class NotIXBRL(Exception):
    """The file is not a parseable iXBRL document."""


@dataclass(frozen=True)
class Fact:
    concept: str      # e.g. "se-gen-base:Nettoomsattning"
    start: str | None  # duration start (None for instants)
    end: str           # duration end or instant
    value: Decimal
    unit: str | None
    decimals: str | None


def parse_number(text: str, fmt: str | None) -> Decimal:
    """Apply the ixt number transformation. The format name says which mark is the decimal one
    (numspacecomma, numdotcomma, numcomma, num-comma-decimal -> ','; numdotdecimal, numcommadot -> '.');
    every other space, dot or comma is digit grouping. No format means plain xs:decimal ('.')."""
    name = (fmt or "").split(":")[-1]
    t = re.sub(r"\s", "", text)
    if name in ("fixedzero", "fixed-zero", "zerodash") or t in ("", "-", "–"):
        return Decimal(0)
    if name.endswith("comma") or "comma-decimal" in name or "commadecimal" in name:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return Decimal(t)
    except InvalidOperation as e:
        raise ValueError(f"cannot parse {text!r} with format {fmt}") from e


def _contexts(root: ET.Element) -> dict[str, tuple[str | None, str]]:
    """context id -> (start, end) for contexts without dimensions (whole-company figures)."""
    out = {}
    for c in root.iter(f"{{{NS['xbrli']}}}context"):
        if c.find("xbrli:entity/xbrli:segment", NS) is not None or c.find("xbrli:scenario", NS) is not None:
            continue
        p = c.find("xbrli:period", NS)
        instant = p.findtext("xbrli:instant", namespaces=NS)
        if instant:
            out[c.get("id")] = (None, instant.strip())
        else:
            out[c.get("id")] = (p.findtext("xbrli:startDate", namespaces=NS).strip(),
                                p.findtext("xbrli:endDate", namespaces=NS).strip())
    return out


def _precision(decimals: str | None) -> float:
    return float("inf") if decimals == "INF" else float(decimals) if decimals not in (None, "") else -1e9


def parse(xhtml: bytes) -> tuple[list[Fact], list[str]]:
    """All whole-company numeric facts, de-duplicated, plus warnings (conflicting duplicates)."""
    try:
        root = ET.fromstring(xhtml)
    except ET.ParseError as e:
        raise NotIXBRL(str(e)) from e
    contexts = _contexts(root)
    if not contexts:
        raise NotIXBRL("no contexts")
    best: dict[tuple, Fact] = {}
    warnings = []
    for el in root.iter(f"{IX}nonFraction"):
        ctx = contexts.get(el.get("contextRef"))
        if ctx is None or el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            continue
        value = parse_number("".join(el.itertext()), el.get("format")) * Decimal(10) ** int(el.get("scale") or 0)
        if el.get("sign") == "-":
            value = -value
        fact = Fact(el.get("name"), ctx[0], ctx[1], value, el.get("unitRef"), el.get("decimals"))
        # shortcut: facts inside ix:tuple (e.g. one row per subsidiary in a note) share a key and
        # collapse to one, showing up as "conflicts". Key metrics are never in tuples; add the
        # tuple id to the key when a note-level table (subsidiaries, loans) is needed.
        key = (fact.concept, fact.start, fact.end)
        prev = best.get(key)
        if prev is None:
            best[key] = fact
            continue
        coarse, fine = sorted((prev, fact), key=lambda f: _precision(f.decimals))
        tolerance = Decimal(10) ** -int(_precision(coarse.decimals)) if coarse.decimals not in (None, "INF") else 0
        if abs(coarse.value - fine.value) > tolerance:
            warnings.append(f"{fact.concept} {fact.end}: {coarse.value} vs {fine.value}")
        best[key] = fine
    return list(best.values()), warnings
