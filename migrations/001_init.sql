-- Reference data published weekly by the pipeline (read-only for users) and per-customer data
-- (organisations, members, watchlists) isolated by row-level security.
create extension if not exists pg_trgm;

-- ---------- reference data ----------
create table companies (
    org_nr          text primary key check (org_nr ~ '^\d{10}$'),
    name            text not null,
    legal_form      text,
    city            text,
    registered_on   date,
    deregistered_on date,
    status          text not null check (status in
                    ('active', 'in_bankruptcy', 'in_liquidation', 'in_reconstruction', 'deregistered'))
);
create index companies_name_trgm on companies using gin (name gin_trgm_ops);

create table risk_scores (
    org_nr          text primary key references companies,
    fiscal_end      date not null,
    filed_on        date not null,
    probability     real not null check (probability between 0 and 1),
    times_average   real not null,
    reasons         text[] not null,
    model_version   text not null
);

create table company_events (
    snapshot_date   date not null,
    org_nr          text not null references companies,
    event           text not null,
    detail          text,
    primary key (org_nr, snapshot_date, event, detail)
);

create table publish_runs (
    id              bigint generated always as identity primary key,
    published_at    timestamptz not null default now(),
    registry_snapshot date not null,
    model_version   text not null,
    companies       int not null,
    scores          int not null,
    events          int not null
);

-- ---------- customer data ----------
create table organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null check (length(trim(name)) between 1 and 200),
    created_at  timestamptz not null default now()
);

create table memberships (
    org_id      uuid not null references organizations on delete cascade,
    user_id     uuid not null,
    role        text not null default 'owner' check (role in ('owner', 'member')),
    primary key (org_id, user_id)
);
create index memberships_user on memberships (user_id);

create table watchlist (
    org_id      uuid not null references organizations on delete cascade,
    org_nr      text not null references companies,
    label       text check (length(label) <= 200),
    added_at    timestamptz not null default now(),
    primary key (org_id, org_nr)
);

-- ---------- row-level security ----------
-- The API runs every user query as `bolagsvakt_app`, with the signed-in user's id in the
-- transaction's request.jwt.claims (see db.as_user). This is our own role on purpose: Supabase
-- serves the `public` schema over its REST API to its built-in `anon` and `authenticated`
-- roles, and granting those roles anything would let any signed-up user download every score
-- around the API. They get nothing here.
do $$ begin
    if not exists (select from pg_roles where rolname = 'bolagsvakt_app') then
        create role bolagsvakt_app nologin;
    end if;
end $$;
grant bolagsvakt_app to current_user;  -- lets the API's login role `set local role bolagsvakt_app`

create function current_user_id() returns uuid language sql stable as $$
    select (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')::uuid
$$;

alter table companies enable row level security;
alter table risk_scores enable row level security;
alter table company_events enable row level security;
alter table publish_runs enable row level security;
alter table organizations enable row level security;
alter table memberships enable row level security;
alter table watchlist enable row level security;

create policy read_all on companies for select to bolagsvakt_app using (true);
create policy read_all on risk_scores for select to bolagsvakt_app using (true);
create policy read_all on company_events for select to bolagsvakt_app using (true);
create policy read_all on publish_runs for select to bolagsvakt_app using (true);

create policy own_memberships on memberships for select to bolagsvakt_app using (user_id = current_user_id());
create policy member_orgs on organizations for select to bolagsvakt_app
    using (id in (select org_id from memberships where user_id = current_user_id()));
create policy member_watchlist on watchlist for all to bolagsvakt_app
    using (org_id in (select org_id from memberships where user_id = current_user_id()))
    with check (org_id in (select org_id from memberships where user_id = current_user_id()));

-- Creating an organisation and its first owner must happen together; users can't insert
-- memberships directly, so this is the only way in.
create function create_organization(org_name text) returns uuid
language plpgsql security definer set search_path = public as $$
declare new_id uuid;
begin
    if current_user_id() is null then
        raise exception 'not signed in';
    end if;
    insert into organizations (name) values (org_name) returning id into new_id;
    insert into memberships (org_id, user_id, role) values (new_id, current_user_id(), 'owner');
    return new_id;
end $$;
revoke all on function create_organization(text) from public;

grant usage on schema public to bolagsvakt_app;
grant select on companies, risk_scores, company_events, publish_runs, organizations, memberships to bolagsvakt_app;
grant select, insert, update, delete on watchlist to bolagsvakt_app;
grant execute on function create_organization(text), current_user_id() to bolagsvakt_app;

-- On Supabase, new tables in `public` are granted to anon/authenticated by default. Take that
-- back, now and for later migrations. (No-op on a plain Postgres, where those roles don't exist.)
do $$
declare r text;
begin
    foreach r in array array['anon', 'authenticated'] loop
        if exists (select from pg_roles where rolname = r) then
            execute format('revoke all on all tables in schema public from %I', r);
            execute format('revoke all on all sequences in schema public from %I', r);
            execute format('revoke all on all functions in schema public from %I', r);
            execute format('alter default privileges in schema public revoke all on tables from %I', r);
            execute format('alter default privileges in schema public revoke all on functions from %I', r);
        end if;
    end loop;
end $$;
