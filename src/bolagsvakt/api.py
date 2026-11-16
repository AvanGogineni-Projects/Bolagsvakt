"""Bolagsvakt API.

    uvicorn bolagsvakt.api:app --reload

Every request that touches customer data runs in a transaction as the signed-in user, so
Postgres row-level security decides what is visible (see db.as_user); the API's own checks are
the second line, not the only one.

Auth: a Supabase access token (Authorization: Bearer ...). Verified with Supabase's published
signing keys when SUPABASE_URL is set, or with SUPABASE_JWT_SECRET (HS256, also used locally).
BOLAGSVAKT_ENV=dev adds POST /v1/dev/token to sign in without Supabase.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from bolagsvakt import orgnr
from bolagsvakt.db import DATABASE_URL, as_user

ENV = os.environ.get("BOLAGSVAKT_ENV", "prod")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
MAX_UPLOAD_BYTES = 1_000_000
MAX_UPLOAD_ROWS = 5_000

pool = ConnectionPool(DATABASE_URL, open=False, kwargs={"row_factory": dict_row})
_jwks = jwt.PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json") if SUPABASE_URL else None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    pool.open()
    yield
    pool.close()


app = FastAPI(title="Bolagsvakt", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])


def current_user(authorization: str = Header(default="")) -> str:
    """The `sub` of a valid, unexpired Supabase access token. Anything else is a 401."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "sign in first")
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256" and JWT_SECRET:
            key = JWT_SECRET
        elif alg in ("ES256", "RS256") and _jwks:
            key = _jwks.get_signing_key_from_jwt(token).key
        else:
            raise jwt.InvalidTokenError(f"unexpected alg {alg}")
        claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated",
                            options={"require": ["exp", "sub"]})
        return str(uuid.UUID(claims["sub"]))
    except (jwt.PyJWTError, ValueError) as e:
        raise HTTPException(401, "invalid or expired token") from e


def user_db(user_id: str = Depends(current_user)):
    with pool.connection() as conn, as_user(conn, user_id):
        yield conn


# scope="function": commit when the endpoint returns, before the response is sent, so a failed
# commit is a 500 and never a "saved" the database didn't keep.
DB = Depends(user_db, scope="function")


def visible_org(conn, org_id: uuid.UUID) -> None:
    """404 unless row-level security lets this user see the organisation."""
    if not conn.execute("select 1 from organizations where id = %s", [org_id]).fetchone():
        raise HTTPException(404, "organisation not found")


@app.get("/health")
def health():
    with pool.connection() as conn:
        last = conn.execute("select published_at, registry_snapshot from publish_runs "
                            "order by id desc limit 1").fetchone()
    return {"ok": True, "last_publish": last}


@app.get("/v1/me")
def me(user_id: str = Depends(current_user), conn=DB):
    orgs = conn.execute("select o.id, o.name, m.role from organizations o join memberships m on m.org_id = o.id "
                        "order by o.created_at").fetchall()
    return {"user_id": user_id, "organizations": orgs}


class NewOrg(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@app.post("/v1/organizations", status_code=201)
def create_org(body: NewOrg, conn=DB):
    org_id = conn.execute("select create_organization(%s) as id", [body.name.strip()]).fetchone()["id"]
    return {"id": org_id, "name": body.name.strip()}


WATCHLIST_SQL = """
select w.org_nr, c.name, c.city, c.status, w.label, w.added_at,
       s.probability, s.times_average, s.reasons, s.fiscal_end
from watchlist w join companies c using (org_nr) left join risk_scores s using (org_nr)
where w.org_id = %s
order by (c.status <> 'active') desc, s.probability desc nulls last, c.name
"""


@app.get("/v1/organizations/{org_id}/watchlist")
def watchlist(org_id: uuid.UUID, conn=DB):
    visible_org(conn, org_id)
    return conn.execute(WATCHLIST_SQL, [org_id]).fetchall()


@app.post("/v1/organizations/{org_id}/watchlist")
def upload_watchlist(org_id: uuid.UUID, file: UploadFile = File(...), conn=DB):
    """CSV (or plain list) with organisation numbers in the first column."""
    visible_org(conn, org_id)
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD_BYTES // 1000} kB")
    text = raw.decode("utf-8-sig") if _is_utf8(raw) else raw.decode("cp1252")  # Excel on Windows saves cp1252
    try:
        cells = orgnr.from_csv(text, MAX_UPLOAD_ROWS)
    except ValueError as e:
        raise HTTPException(413, str(e)) from e
    valid = {n: c for c in cells if (n := orgnr.normalize(c))}
    invalid = [c for c in cells if not orgnr.normalize(c)]
    known = {r["org_nr"] for r in conn.execute("select org_nr from companies where org_nr = any(%s)",
                                               [list(valid)]).fetchall()}
    added = conn.execute("insert into watchlist (org_id, org_nr) select %s, unnest(%s::text[]) "
                         "on conflict do nothing", [org_id, sorted(known)]).rowcount
    return {"added": added, "already_watched": len(known) - added,
            "unknown": sorted(valid[n] for n in valid if n not in known),
            "invalid": invalid[:100], "invalid_count": len(invalid)}


def _is_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


@app.delete("/v1/organizations/{org_id}/watchlist/{org_nr}", status_code=204)
def unwatch(org_id: uuid.UUID, org_nr: str, conn=DB):
    visible_org(conn, org_id)
    conn.execute("delete from watchlist where org_id = %s and org_nr = %s", [org_id, org_nr])
    return Response(status_code=204)


@app.get("/v1/organizations/{org_id}/events")
def events(org_id: uuid.UUID, days: int = 90, conn=DB):
    visible_org(conn, org_id)
    since = dt.date.today() - dt.timedelta(days=min(max(days, 1), 730))
    return conn.execute("""select e.snapshot_date, e.org_nr, c.name, e.event, e.detail
                           from company_events e join watchlist w on w.org_nr = e.org_nr and w.org_id = %s
                           join companies c on c.org_nr = e.org_nr
                           where e.snapshot_date >= %s order by e.snapshot_date desc, c.name""",
                        [org_id, since]).fetchall()


@app.get("/v1/companies/{org_nr}")
def company(org_nr: str, conn=DB):
    nr = orgnr.normalize(org_nr)
    row = nr and conn.execute("""select c.*, s.probability, s.times_average, s.reasons, s.fiscal_end, s.filed_on,
                                        s.model_version
                                 from companies c left join risk_scores s using (org_nr)
                                 where c.org_nr = %s""", [nr]).fetchone()
    if not row:
        raise HTTPException(404, "company not found")
    row["events"] = conn.execute("select snapshot_date, event, detail from company_events where org_nr = %s "
                                 "order by snapshot_date desc limit 50", [nr]).fetchall()
    return row


@app.get("/v1/search")
def search(q: str, conn=DB):
    q = q.strip()
    if len(q) < 2:
        return []
    digits = q.replace("-", "")
    if digits.isdigit():
        return conn.execute("select org_nr, name, city, status from companies where org_nr like %s "
                            "order by org_nr limit 20", [digits + "%"]).fetchall()
    return conn.execute("""select org_nr, name, city, status from companies
                           where name ilike %s order by (status = 'active') desc, similarity(name, %s) desc
                           limit 20""", ["%" + q + "%", q]).fetchall()


if ENV == "dev":
    class DevLogin(BaseModel):
        email: str = Field(min_length=3, max_length=200)

    @app.post("/v1/dev/token")
    def dev_token(body: DevLogin):
        """Local sign-in without Supabase: a short-lived token shaped like Supabase's."""
        if not JWT_SECRET:
            raise HTTPException(500, "set SUPABASE_JWT_SECRET for dev tokens")
        sub = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bolagsvakt-dev:{body.email.lower()}"))
        exp = dt.datetime.now(dt.UTC) + dt.timedelta(hours=8)
        token = jwt.encode({"sub": sub, "aud": "authenticated", "exp": exp, "email": body.email},
                           JWT_SECRET, algorithm="HS256")
        return {"access_token": token}
