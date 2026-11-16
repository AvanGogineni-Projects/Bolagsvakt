import io
import zipfile
from decimal import Decimal

import pytest

from bolagsvakt.annual_reports import metrics_for, process_part
from bolagsvakt.ixbrl import NotIXBRL, parse, parse_number


def report(body: str, contexts: str) -> bytes:
    return f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:se-gen-base="x"><body>
      <ix:header><ix:resources>{contexts}</ix:resources></ix:header>{body}</body></html>""".encode()


def ctx(cid, start=None, end="2025-12-31", dims=False):
    period = (f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
              if start else f"<xbrli:instant>{end}</xbrli:instant>")
    seg = "<xbrli:segment>dim</xbrli:segment>" if dims else ""
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>{seg}'
            f"</xbrli:entity><xbrli:period>{period}</xbrli:period></xbrli:context>")


def nf(name, cref, text, scale=0, decimals="0", sign=None, fmt="ixt:numspacecomma"):
    s = f' sign="{sign}"' if sign else ""
    return (f'<ix:nonFraction name="se-gen-base:{name}" contextRef="{cref}" scale="{scale}" '
            f'decimals="{decimals}" format="{fmt}" unitRef="SEK"{s}>{text}</ix:nonFraction>')


CONTEXTS = (ctx("period0", "2025-01-01", "2025-12-31") + ctx("balans0", end="2025-12-31")
            + ctx("period1", "2024-01-01", "2024-12-31") + ctx("balans1", end="2024-12-31")
            + ctx("dim0", "2025-01-01", "2025-12-31", dims=True))


@pytest.mark.parametrize("text,fmt,expected", [
    ("1 234 567", "ixt:numspacecomma", "1234567"),
    ("3,6", "ixt:numspacecomma", "3.6"),
    ("1.234,5", "ixt:numdotcomma", "1234.5"),
    ("1,234.5", "ixt:numcommadot", "1234.5"),
    ("12,5", "ixt:numcomma", "12.5"),
    ("1234.5", None, "1234.5"),
    ("-", "ixt:numspacecomma", "0"),
    ("1 000", "ixt:numspacecomma", "1000"),
])
def test_number_formats(text, fmt, expected):
    assert parse_number(text, fmt) == Decimal(expected)


def test_scale_sign_precision_and_dimensions():
    facts, warnings = parse(report(
        nf("Nettoomsattning", "period0", "750", scale=3, decimals="-3")        # summary, in thousands
        + nf("Nettoomsattning", "period0", "750 221")                         # statement, exact: wins
        + nf("AretsResultat", "period0", "12 000", sign="-")                  # a loss
        + nf("Soliditet", "balans0", "3,6", scale=-2, decimals="INF")
        + nf("Nettoomsattning", "dim0", "999"),                               # per-segment: not company total
        CONTEXTS))
    got = {(f.concept.split(":")[1], f.end): f.value for f in facts}
    assert got == {("Nettoomsattning", "2025-12-31"): Decimal(750221),
                   ("AretsResultat", "2025-12-31"): Decimal(-12000),
                   ("Soliditet", "2025-12-31"): Decimal("0.036")}
    assert warnings == []


def test_conflicting_duplicates_are_reported_not_hidden():
    _, warnings = parse(report(nf("EgetKapital", "balans0", "5 062", scale=3, decimals="-3")
                               + nf("EgetKapital", "balans0", "4 135 362"), CONTEXTS))
    assert warnings == ["se-gen-base:EgetKapital 2025-12-31: 5062000 vs 4135362"]


def test_prior_year_needs_an_income_period_not_an_opening_balance():
    first_year = report(nf("EgetKapital", "balans0", "100") + nf("Aktiekapital", "open", "25 000"),
                        CONTEXTS + ctx("open", end="2025-03-01"))
    assert set(metrics_for(parse(first_year)[0], "2025-12-31")) == {"current"}
    second_year = report(nf("EgetKapital", "balans0", "100") + nf("EgetKapital", "balans1", "50")
                         + nf("Nettoomsattning", "period1", "10"), CONTEXTS)
    m = metrics_for(parse(second_year)[0], "2025-12-31")
    assert (m["prior"]["period_end"], m["prior"]["equity"], m["prior"]["revenue"]) == ("2024-12-31", 50.0, 10.0)


def test_part_picks_annual_report_over_audit_report_and_keeps_bad_filings_as_rejects(tmp_path):
    annual = report(nf("EgetKapital", "balans0", "100") + nf("Tillgangar", "balans0", "300"), CONTEXTS)
    audit = report(nf("EgetKapital", "balans0", "1"), CONTEXTS)
    part = tmp_path / "part.zip"
    with zipfile.ZipFile(part, "w") as outer:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as inner:
            inner.writestr("b-audit.xhtml", audit)
            inner.writestr("a-report.xhtml", annual)
        outer.writestr("5560000001_2025-12-31.zip", buf.getvalue())
        outer.writestr("5560000002_2025-12-31.zip", b"not a zip")
    t = process_part(part, "2026_01_1")
    (row,) = t["metrics"]
    assert (row["org_nr"], row["equity"], row["total_assets"], row["has_audit_report"]) == ("5560000001", 100, 300, True)
    assert [r["file"] for r in t["rejects"]] == ["5560000002_2025-12-31.zip"]


def test_not_xml_is_rejected():
    with pytest.raises(NotIXBRL):
        parse(b"<html><body>unclosed")


def test_download_retries_a_dropped_connection_and_gives_up_on_404(tmp_path):
    import httpx

    from bolagsvakt.annual_reports import download
    calls = []

    def handler(request):
        calls.append(1)
        if request.url.path == "/missing":
            return httpx.Response(404)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("peer closed connection")
        return httpx.Response(200, content=b"zipbytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with open(tmp_path / "f", "w+b") as f:
        download(client, "https://x/part", f, sleep=lambda s: None)
        f.seek(0)
        assert f.read() == b"zipbytes" and len(calls) == 2
        with pytest.raises(httpx.HTTPStatusError):
            download(client, "https://x/missing", f, sleep=lambda s: None)
