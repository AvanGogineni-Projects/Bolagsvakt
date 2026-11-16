import datetime as dt
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from bolagsvakt import api, orgnr
from tests.conftest import TEST_DB

SECRET = "test-secret-at-least-32-bytes-long!!"


def nr(prefix9: str) -> str:
    """A valid organisation number: the 9 digits plus their Luhn check digit."""
    return next(prefix9 + str(d) for d in range(10) if orgnr.luhn_ok(prefix9 + str(d)))


A, B, C = nr("556000000"), nr("556000001"), nr("556000002")


def token(user: str, **over) -> dict:
    claims = {"sub": user, "aud": "authenticated", "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)} | over
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


@pytest.fixture
def client(db, monkeypatch):
    with db.transaction():
        for org, name, status in [(A, "Alfa AB", "active"), (B, "Beta AB", "in_bankruptcy"), (C, "Gamma Bygg AB", "active")]:
            db.execute("insert into companies (org_nr, name, city, status) values (%s, %s, 'LUND', %s)",
                       [org, name, status])
        db.execute("insert into risk_scores values (%s, '2025-12-31', '2026-03-01', 0.2, 10, "
                   "array['Equity is negative: debts exceed assets'], 'risk_v1')", [A])
        db.execute("insert into company_events values (current_date, %s, 'proceeding_started', 'KK-AVOMFO'),"
                   "(current_date, %s, 'address_changed', 'x -> y')", [B, C])
    monkeypatch.setattr(api, "JWT_SECRET", SECRET)
    monkeypatch.setattr(api, "pool", ConnectionPool(TEST_DB, open=False, kwargs={"row_factory": dict_row}))
    with TestClient(api.app) as c:
        yield c


def org_with_list(client, user, csv: str):
    org = client.post("/v1/organizations", json={"name": "Kund AB"}, headers=token(user)).json()["id"]
    r = client.post(f"/v1/organizations/{org}/watchlist", files={"file": ("list.csv", csv.encode())},
                    headers=token(user))
    return org, r


def test_requests_need_a_valid_unexpired_token(client):
    user = str(uuid.uuid4())
    assert client.get("/v1/me").status_code == 401
    forged = jwt.encode({"sub": user, "aud": "authenticated", "exp": 9999999999}, "wrong", algorithm="HS256")
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = token(user, exp=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1))
    assert client.get("/v1/me", headers=expired).status_code == 401
    assert client.get("/v1/me", headers=token(user)).json() == {"user_id": user, "organizations": []}


def test_upload_reports_what_happened_to_every_row(client):
    user = str(uuid.uuid4())
    bad_check = A[:-1] + str((int(A[-1]) + 1) % 10)
    csv = f"org_nr;name\n{A[:6]}-{A[6:]};Alfa\n{B}\n{B}\n{nr('556999999')}\n{bad_check}\n"
    org, r = org_with_list(client, user, csv)
    assert r.json() == {"added": 2, "already_watched": 0, "unknown": [nr("556999999")],
                        "invalid": ["org_nr", bad_check], "invalid_count": 2}
    again = client.post(f"/v1/organizations/{org}/watchlist", files={"file": ("l.csv", A.encode())}, headers=token(user))
    assert again.json()["already_watched"] == 1
    rows = client.get(f"/v1/organizations/{org}/watchlist", headers=token(user)).json()
    # companies already in proceedings first, then by risk
    assert [(r["org_nr"], r["status"], r["reasons"]) for r in rows] == [
        (B, "in_bankruptcy", None), (A, "active", ["Equity is negative: debts exceed assets"])]


def test_other_customers_get_404_not_data(client):
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    org, _ = org_with_list(client, alice, A)
    for method, path in [("get", "watchlist"), ("get", "events"), ("delete", f"watchlist/{A}")]:
        assert getattr(client, method)(f"/v1/organizations/{org}/{path}", headers=token(bob)).status_code == 404
    up = client.post(f"/v1/organizations/{org}/watchlist", files={"file": ("l.csv", B.encode())}, headers=token(bob))
    assert up.status_code == 404
    assert len(client.get(f"/v1/organizations/{org}/watchlist", headers=token(alice)).json()) == 1


def test_events_feed_only_shows_watched_companies(client):
    user = str(uuid.uuid4())
    org, _ = org_with_list(client, user, B)
    feed = client.get(f"/v1/organizations/{org}/events", headers=token(user)).json()
    assert [(e["org_nr"], e["event"]) for e in feed] == [(B, "proceeding_started")]


def test_unwatch(client):
    user = str(uuid.uuid4())
    org, _ = org_with_list(client, user, f"{A}\n{B}")
    assert client.delete(f"/v1/organizations/{org}/watchlist/{A}", headers=token(user)).status_code == 204
    assert [r["org_nr"] for r in client.get(f"/v1/organizations/{org}/watchlist", headers=token(user)).json()] == [B]


def test_company_page_and_search(client):
    h = token(str(uuid.uuid4()))
    page = client.get(f"/v1/companies/{A[:6]}-{A[6:]}", headers=h).json()
    assert (page["name"], page["probability"], page["events"]) == ("Alfa AB", pytest.approx(0.2), [])
    assert client.get("/v1/companies/123", headers=h).status_code == 404
    assert [r["org_nr"] for r in client.get("/v1/search", params={"q": "bygg"}, headers=h).json()] == [C]
    assert [r["org_nr"] for r in client.get("/v1/search", params={"q": A[:9]}, headers=h).json()] == [A]


def test_upload_limits(client):
    user = str(uuid.uuid4())
    org = client.post("/v1/organizations", json={"name": "Kund AB"}, headers=token(user)).json()["id"]
    big = client.post(f"/v1/organizations/{org}/watchlist", files={"file": ("l.csv", b"1" * 1_000_001)},
                      headers=token(user))
    assert big.status_code == 413
    many = client.post(f"/v1/organizations/{org}/watchlist",
                       files={"file": ("l.csv", ("\n".join([A] * 5001)).encode())}, headers=token(user))
    assert many.status_code == 413


def test_orgnr_normalize():
    assert orgnr.normalize(f"16{A[:6]}-{A[6:]}") == A
    assert orgnr.normalize(" 12345 ") is None
