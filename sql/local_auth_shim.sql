-- Local stand-in for what Supabase already provides: the `authenticated` role and auth.uid().
-- Apply only to a local Postgres; on Supabase these exist and must not be replaced.
do $$ begin
  if not exists (select from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end $$;

create schema if not exists auth;

-- Same contract as Supabase: the user id is the `sub` claim of the request's JWT,
-- set per transaction by the API with set_config('request.jwt.claims', ..., true).
-- Matches Supabase's definition, including the empty-string case: after a transaction that set
-- the claims ends, the setting reads back as '' rather than NULL.
create or replace function auth.uid() returns uuid language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;

grant usage on schema auth to authenticated;
