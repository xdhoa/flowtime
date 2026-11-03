-- Migration 002: the manager can decline a request (new status 'declined') and reopen it.
-- Run in Supabase SQL Editor after 001. Safe on a live database and safe to re-run:
-- it widens the allowed status list and adds one function. No existing data changes.

do $$
declare c text;
begin
  -- Replace the original status check (auto-named by PostgreSQL) with one that also allows 'declined'.
  for c in
    select conname from pg_constraint
    where conrelid = 'public.tasks'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) like '%status%' and pg_get_constraintdef(oid) not like '%declined%'
  loop
    execute format('alter table public.tasks drop constraint %I', c);
  end loop;
  if not exists (select 1 from pg_constraint where conname = 'tasks_status_allowed') then
    alter table public.tasks add constraint tasks_status_allowed
      check (status in ('new','accepted','doing','waiting','review','delivered','declined'));
  end if;
end $$;

-- Decline atomically: stop any running timer on the task, then mark it declined.
create or replace function public.task_decline(p_manager uuid, p_task uuid) returns jsonb
language plpgsql security definer set search_path = public as $$
declare st text;
begin
  perform pg_advisory_xact_lock(hashtext(p_manager::text));
  select status into st from public.tasks where id = p_task for update;
  if st is null then raise exception 'Task not found'; end if;
  if st in ('delivered', 'declined') then raise exception 'Task cannot be declined'; end if;
  update public.sessions set ended_at = now() where manager_id = p_manager and task_id = p_task and ended_at is null;
  update public.tasks set status = 'declined', updated_at = now() where id = p_task;
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.task_decline(uuid, uuid) from public, anon, authenticated;
grant execute on function public.task_decline(uuid, uuid) to service_role;
