-- Run ONCE in Supabase SQL Editor. Dedicated project recommended.
create extension if not exists pgcrypto;
create table public.tasks (
 id uuid primary key default gen_random_uuid(), requester_id uuid not null references auth.users(id),
 requester_email text not null, requester_name text not null,
 title text not null, description text not null default '', deliverable text not null default '',
 category text not null default 'Khác', collaborators text not null default '', attachment_url text not null default '',
 requested_deadline timestamptz not null, committed_deadline timestamptz,
 status text not null default 'new' check (status in ('new','accepted','doing','waiting','review','delivered')),
 result text not null default '', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index on public.tasks(requester_id,created_at desc);
create table public.plans (
 task_id uuid primary key references public.tasks(id) on delete cascade,
 estimate_minutes numeric not null check(estimate_minutes>0 and estimate_minutes<=100000),
 priority integer not null default 2 check(priority between 1 and 3),
 ai_estimate jsonb, private_notes text not null default ''
);
create table public.sessions (
 id uuid primary key default gen_random_uuid(), manager_id uuid not null references auth.users(id),
 task_id uuid not null references public.tasks(id) on delete cascade,
 started_at timestamptz not null default now(), ended_at timestamptz,
 check(ended_at is null or ended_at>=started_at)
);
create unique index one_running_timer on public.sessions(manager_id) where ended_at is null;
create table public.events (
 id uuid primary key default gen_random_uuid(), task_id uuid not null references public.tasks(id) on delete cascade,
 actor_id uuid not null references auth.users(id), actor_name text not null, body text not null,
 created_at timestamptz not null default now()
);
create index on public.events(task_id,created_at);
create table public.settings (manager_id uuid primary key references auth.users(id), value jsonb not null);
create table public.quotas (user_id uuid not null references auth.users(id),kind text not null,day date not null default current_date,used integer not null default 0,primary key(user_id,kind,day));
create table public.mail_log (key text primary key,provider_id text,created_at timestamptz not null default now());
grant all on public.tasks,public.plans,public.sessions,public.events,public.settings,public.quotas,public.mail_log to service_role;
-- Every data operation passes through authenticated server handlers. Clients have NO direct table access.
-- The service_role key stays on the server. Manager identity is a server-only UUID, never user metadata.
-- Explicit statements (not a loop) so Supabase's SQL Editor recognises that RLS is enabled.
alter table public.tasks enable row level security;
alter table public.plans enable row level security;
alter table public.sessions enable row level security;
alter table public.events enable row level security;
alter table public.settings enable row level security;
alter table public.quotas enable row level security;
alter table public.mail_log enable row level security;
revoke all on public.tasks,public.plans,public.sessions,public.events,public.settings,public.quotas,public.mail_log from anon, authenticated;

create function public.consume_quota(p_user uuid,p_kind text,p_limit integer) returns boolean
language plpgsql security definer set search_path=public as $$
declare n integer; begin
 insert into public.quotas(user_id,kind,used) values(p_user,p_kind,1)
 on conflict(user_id,kind,day) do update set used=quotas.used+1 where quotas.used<p_limit
 returning used into n; return n is not null; end $$;
revoke all on function public.consume_quota(uuid,text,integer) from public,anon,authenticated;
grant execute on function public.consume_quota(uuid,text,integer) to service_role;

-- Atomic timer switch across tabs, devices and concurrent requests.
create function public.timer_change(p_manager uuid,p_task uuid,p_action text) returns jsonb
language plpgsql security definer set search_path=public as $$
declare st text; begin
 perform pg_advisory_xact_lock(hashtext(p_manager::text));
 select status into st from public.tasks where id=p_task for update;
 if st is null then raise exception 'Task not found'; end if;
 if p_action not in ('start','pause') then raise exception 'Invalid action'; end if;
 if p_action='start' and st not in ('accepted','doing') then raise exception 'Task must be accepted before start'; end if;
 if p_action='pause' then
 update public.sessions set ended_at=now() where manager_id=p_manager and task_id=p_task and ended_at is null;
 else
 if exists(select 1 from public.sessions where manager_id=p_manager and task_id=p_task and ended_at is null) then return jsonb_build_object('ok',true); end if;
 update public.sessions set ended_at=now() where manager_id=p_manager and ended_at is null;
 update public.tasks set status='accepted',updated_at=now() where status='doing' and id<>p_task;
 insert into public.sessions(manager_id,task_id) values(p_manager,p_task);
 update public.tasks set status='doing',updated_at=now() where id=p_task;
 end if;
 return jsonb_build_object('ok',true); end $$;
revoke all on function public.timer_change(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.timer_change(uuid,uuid,text) to service_role;

-- Review/handoff state transitions also stop the timer in the same transaction.
create function public.task_status(p_manager uuid,p_task uuid,p_status text,p_result text) returns jsonb
language plpgsql security definer set search_path=public as $$
begin
 perform pg_advisory_xact_lock(hashtext(p_manager::text));
 if p_status not in ('accepted','waiting','review','delivered') then raise exception 'Invalid status'; end if;
 perform 1 from public.tasks where id=p_task for update;
 if not found then raise exception 'Task not found'; end if;
 update public.sessions set ended_at=now() where manager_id=p_manager and task_id=p_task and ended_at is null;
 update public.tasks set status=p_status,result=coalesce(p_result,''),updated_at=now() where id=p_task;
 return jsonb_build_object('ok',true); end $$;
revoke all on function public.task_status(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.task_status(uuid,uuid,text,text) to service_role;
