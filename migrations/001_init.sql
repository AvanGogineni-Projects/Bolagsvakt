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
alter table companies enable row level security;
alter table risk_scores enable row level security;
alter table company_events enable row level security;
alter table publish_runs enable row level security;
alter table organizations enable row level security;
alter table memberships enable row level security;
alter table watchlist enable row level security;

create policy read_all on companies for select to authenticated using (true);
create policy read_all on risk_scores for select to authenticated using (true);
create policy read_all on company_events for select to authenticated using (true);
create policy read_all on publish_runs for select to authenticated using (true);

create policy own_memberships on memberships for select to authenticated using (user_id = auth.uid());
create policy member_orgs on organizations for select to authenticated
    using (id in (select org_id from memberships where user_id = auth.uid()));
create policy member_watchlist on watchlist for all to authenticated
    using (org_id in (select org_id from memberships where user_id = auth.uid()))
    with check (org_id in (select org_id from memberships where user_id = auth.uid()));

-- Creating an organisation and its first owner must happen together; users can't insert
-- memberships directly, so this is the only way in.
create function create_organization(org_name text) returns uuid
language plpgsql security definer set search_path = public as $$
declare new_id uuid;
begin
    if auth.uid() is null then
        raise exception 'not signed in';
    end if;
    insert into organizations (name) values (org_name) returning id into new_id;
    insert into memberships (org_id, user_id, role) values (new_id, auth.uid(), 'owner');
    return new_id;
end $$;
revoke all on function create_organization(text) from public;

grant usage on schema public to authenticated;
grant select on companies, risk_scores, company_events, publish_runs, organizations, memberships to authenticated;
grant select, insert, update, delete on watchlist to authenticated;
grant execute on function create_organization(text) to authenticated;
