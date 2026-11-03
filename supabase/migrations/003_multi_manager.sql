-- Migration 003: many managers. Every account is a manager with a private workspace and a
-- personal request link (#request/<slug>). Run after 002. Safe to re-run; adds, never deletes.

-- Each manager's public code (slug) used in their request link.
create table if not exists public.managers (
  user_id uuid primary key references auth.users(id) on delete cascade,
  slug text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'),
  name text not null default '',
  email text not null default '',
  created_at timestamptz not null default now()
);
alter table public.managers enable row level security;
revoke all on public.managers from anon, authenticated;
grant all on public.managers to service_role;

-- Which manager a request belongs to.
alter table public.tasks add column if not exists manager_id uuid references auth.users(id);
create index if not exists tasks_manager_created on public.tasks(manager_id, created_at desc);
-- If you already used the single-manager version, give old requests to that manager once:
--   update public.tasks set manager_id = '<old FLOWTIME_MANAGER_ID uuid>' where manager_id is null;

-- Transaction functions now only act on the calling manager's own tasks.
create or replace function public.timer_change(p_manager uuid, p_task uuid, p_action text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare st text; begin
  perform pg_advisory_xact_lock(hashtext(p_manager::text));
  select status into st from public.tasks where id = p_task and manager_id = p_manager for update;
  if st is null then raise exception 'Task not found'; end if;
  if p_action not in ('start', 'pause') then raise exception 'Invalid action'; end if;
  if p_action = 'start' and st not in ('accepted', 'doing') then raise exception 'Task must be accepted before start'; end if;
  if p_action = 'pause' then
    update public.sessions set ended_at = now() where manager_id = p_manager and task_id = p_task and ended_at is null;
  else
    if exists (select 1 from public.sessions where manager_id = p_manager and task_id = p_task and ended_at is null) then
      return jsonb_build_object('ok', true);
    end if;
    update public.sessions set ended_at = now() where manager_id = p_manager and ended_at is null;
    update public.tasks set status = 'accepted', updated_at = now() where status = 'doing' and id <> p_task and manager_id = p_manager;
    insert into public.sessions(manager_id, task_id) values (p_manager, p_task);
    update public.tasks set status = 'doing', updated_at = now() where id = p_task;
  end if;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.task_status(p_manager uuid, p_task uuid, p_status text, p_result text) returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  perform pg_advisory_xact_lock(hashtext(p_manager::text));
  if p_status not in ('accepted', 'waiting', 'review', 'delivered') then raise exception 'Invalid status'; end if;
  perform 1 from public.tasks where id = p_task and manager_id = p_manager for update;
  if not found then raise exception 'Task not found'; end if;
  update public.sessions set ended_at = now() where manager_id = p_manager and task_id = p_task and ended_at is null;
  update public.tasks set status = p_status, result = coalesce(p_result, ''), updated_at = now() where id = p_task;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.task_decline(p_manager uuid, p_task uuid) returns jsonb
language plpgsql security definer set search_path = public as $$
declare st text;
begin
  perform pg_advisory_xact_lock(hashtext(p_manager::text));
  select status into st from public.tasks where id = p_task and manager_id = p_manager for update;
  if st is null then raise exception 'Task not found'; end if;
  if st in ('delivered', 'declined') then raise exception 'Task cannot be declined'; end if;
  update public.sessions set ended_at = now() where manager_id = p_manager and task_id = p_task and ended_at is null;
  update public.tasks set status = 'declined', updated_at = now() where id = p_task;
  return jsonb_build_object('ok', true);
end $$;

revoke all on function public.timer_change(uuid, uuid, text) from public, anon, authenticated;
revoke all on function public.task_status(uuid, uuid, text, text) from public, anon, authenticated;
revoke all on function public.task_decline(uuid, uuid) from public, anon, authenticated;
grant execute on function public.timer_change(uuid, uuid, text) to service_role;
grant execute on function public.task_status(uuid, uuid, text, text) to service_role;
grant execute on function public.task_decline(uuid, uuid) to service_role;
