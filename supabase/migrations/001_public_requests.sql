-- Migration 001: submit requests WITHOUT signing in (only the manager signs in).
-- Run in Supabase SQL Editor AFTER schema.sql. Safe on a live database and safe to re-run:
-- it only relaxes two NOT NULL constraints and adds a column, an index, a check, a table and a function.
-- Existing rows and data are not changed.

-- Guest requests have no auth user; they are identified by a secret tracking-link token (stored hashed).
alter table public.tasks alter column requester_id drop not null;
alter table public.tasks add column if not exists guest_token_hash text;
create unique index if not exists tasks_guest_token_hash_key on public.tasks(guest_token_hash) where guest_token_hash is not null;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'tasks_owner_present') then
    alter table public.tasks add constraint tasks_owner_present check (requester_id is not null or guest_token_hash is not null);
  end if;
end $$;

-- Guest comments have no auth user id; actor_name still records who wrote them.
alter table public.events alter column actor_id drop not null;

-- Daily limits for anonymous use, keyed by a hashed visitor key or 'all' (global cap).
create table if not exists public.guest_quotas (
  key text not null, kind text not null, day date not null default current_date,
  used integer not null default 0, primary key (key, kind, day)
);
alter table public.guest_quotas enable row level security;
revoke all on table public.guest_quotas from anon, authenticated;
grant all on public.guest_quotas to service_role;

create or replace function public.consume_guest_quota(p_key text, p_kind text, p_limit integer) returns boolean
language plpgsql security definer set search_path = public as $$
declare n integer; begin
  insert into public.guest_quotas(key, kind, used) values (p_key, p_kind, 1)
  on conflict (key, kind, day) do update set used = guest_quotas.used + 1 where guest_quotas.used < p_limit
  returning used into n;
  return n is not null;
end $$;
revoke all on function public.consume_guest_quota(text, text, integer) from public, anon, authenticated;
grant execute on function public.consume_guest_quota(text, text, integer) to service_role;
