# Flowtime 3.0

**Clear requests. Work in rhythm.** (UI: *Giao việc rõ ràng. Làm việc có nhịp.*)

Flowtime is a task-request and personal workload app for **many managers**. **Requesters** submit work to a manager and approve results. Each **manager** reviews requests, commits to deadlines, schedules work, tracks actual time, and hands over results. AI helps draft requests, estimate effort, and suggest improvements. The manager must confirm every consequential change.

Version 3.0 moves the backend from Node.js to **Python + Flask**, and the app no longer needs a Node.js server. Vietnamese step-by-step deployment guide: **[GO_LIVE_VI.md](GO_LIVE_VI.md)**.

## Who signs in, and how requests reach a manager

- **Managers sign up themselves** (`/#login` → *Tạo tài khoản quản lý*) and confirm their email. Every account is a manager with a private workspace: their own requests, roadmap, timer, working hours and reports.
- **Each manager gets a personal request link**, `/#request/<code>`, shown on their dashboard with a copy button. The code is created from the manager's name (e.g. `ngoc-hoa`) and can be changed under *Đổi mã*.
- **Requesters need no account.** They open a manager's link, see "Gửi yêu cầu cho <name>", and submit with their name and email. The request goes only to that manager. Opening the bare app address asks for the manager's code.
- After submitting, the requester gets a private tracking link (`/#track=<token>`), also remembered on that device. With it they can follow status, comment and approve the result. Anyone holding the link can see that one request, but nothing else.
- Public submissions are protected by a hidden honeypot field and daily limits: 10 requests, 5 AI drafts and 100 comments per visitor, plus global caps of 300, 100 and 2000. Only a hash of the tracking token is stored.
- Total AI calls across all managers are capped per day by `AI_DAILY_LIMIT` (default 300), so open sign-up cannot run up your OpenAI bill. To stop new sign-ups entirely, turn off *Allow new users to sign up* in Supabase Auth.
- Database: run `schema.sql`, then the migrations in [`supabase/migrations/`](supabase/migrations/) in order (001, 002, 003). They are additive and safe to re-run.

## Architecture

| Part | Technology |
|---|---|
| Backend | Python 3.12+ / Flask (`app.py`, `flowtime/`) |
| UI | HTML/CSS/JavaScript in `public/` (no build step) |
| Accounts + database | Supabase Auth + PostgreSQL |
| AI | OpenAI Responses API (Structured Outputs) |
| Outgoing email (optional) | Resend |
| Hosting | Vercel (zero-config Flask + daily cron). Render as an alternative (`render.yaml`) |
| Source | GitHub |

GitHub Pages alone **cannot** run this app. It only serves static files, and Flowtime needs a server that keeps the API keys secret and checks permissions.

## Run on Windows (VS Code terminal)

1. Install **Python 3.12 or newer** from https://www.python.org/downloads/. In the installer, tick **"Add python.exe to PATH"**.
2. In VS Code: **File → Open Folder** and open the `flowtime-github` folder (the one that contains `app.py`).
3. **Terminal → New Terminal**, then run these once:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   ```

   If PowerShell says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, and activate again.
4. Start the app:

   ```powershell
   python app.py
   ```

5. Open http://localhost:3000 and click **Mở demo tương tác** (interactive demo). Press `Ctrl+C` in the terminal to stop.

Next time, you only need `.\.venv\Scripts\Activate.ps1` and then `python app.py`.

**Demo mode** works without any accounts. It uses sample data stored only in your browser, has a role switch, and does not call AI or send email. For real use, copy `.env.example` to `.env` and fill in the values (see Configuration). `app.py` reads `.env` automatically.

## Tests

```powershell
python -m pytest -q
```

This runs 84 tests covering manager isolation, the public request flow, authorization, input validation, the scheduler, AI error handling, cron protection, and static file serving. If Node.js is installed, you can also test the browser modules (demo flow and the JS planner) with `node --test "tests/frontend/*.test.mjs"`. These tests are optional; Node is not used to run the app.

## Configuration

| Variable | Required for | Purpose |
|---|---|---|
| `SUPABASE_URL` | Real use | Supabase project URL |
| `SUPABASE_ANON_KEY` | Real use | Anon/publishable key (used for Auth calls) |
| `SUPABASE_SERVICE_ROLE_KEY` | Real use | Secret service-role key. Server only |
| `APP_URL` | Real use | Public base URL, e.g. `https://my-flowtime.vercel.app` |
| `OPENAI_API_KEY` | AI | OpenAI API key |
| `OPENAI_MODEL` | AI (default `gpt-4.1-mini`) | Any Responses model with Structured Outputs |
| `AI_DAILY_LIMIT` | AI (default 300) | Total AI calls per day across all managers |
| `RESEND_API_KEY`, `EMAIL_FROM` | Email | Handoff email + daily digest (sent to each manager's account email) |
| `CRON_SECRET` | Digest | Random string, at least 32 characters |
| `PORT` | Local only | Default 3000 |

Never commit `.env` or keys. `.gitignore` already excludes `.env` and `.venv/`.

## Security model

- **Manager isolation:** every task has a `manager_id`. Every endpoint verifies the Supabase access token on the server, reads only rows belonging to the signed-in manager, and checks ownership before any change. Another manager guessing a task ID gets 404. Permissions never come from browser input or user metadata.
- **Database:** RLS is enabled and the `anon`/`authenticated` roles have no table access. Only the server, using the service-role key, can reach the tables.
- **Requesters** (tracking-link holders) see only the shared brief, status, deadlines, result and discussion. Plans, time logs, private notes, settings and workload analysis are never sent to them.
- **Timer, status and decline changes** run as PostgreSQL transactions (`timer_change`, `task_status`, `task_decline`) that also check `manager_id`, so each manager has one running timer at a time, across tabs and devices, and can only affect their own tasks.
- **Cross-site POSTs** are blocked: the `Origin` header must match `APP_URL` or the request's own host. `/api/cron` rejects requests without the correct `CRON_SECRET`.
- **AI output is advisory.** Plans change only when the manager explicitly submits them. The AI prompt treats request text as untrusted data.
- **Per-account daily quotas** (UTC days) are enforced in the database: 50 AI calls, 50 requests, 200 comments, 50 handoff emails, plus the global `AI_DAILY_LIMIT`.

## API (unchanged from 2.x)

```
GET  /api/index?route=config                 public; never returns secrets
GET  /api/index?route=data                   signed-in user's view (role-filtered)
GET  /api/index?route=tasks/<id>/events      discussion/history
POST /api/index?route=tasks                  create request (requester identity bound by server)
POST /api/index?route=settings               manager: working hours and busy periods
POST /api/index?route=ai                     parse (anyone) | estimate, advice (manager)
POST /api/index?route=tasks/<id>/comment     shared discussion
POST /api/index?route=tasks/<id>/accept      requester approves a result in review
POST /api/index?route=tasks/<id>/plan|timer|status|handoff     manager only
POST /api/index?route=auth/login|signup|refresh|recover|logout|password
POST /api/index?route=public/tasks           no sign-in: submit request, returns tracking token once
POST /api/index?route=public/track|comment|accept   no sign-in: requires {"token": ...}
POST /api/index?route=public/ai              no sign-in: AI draft (rate-limited)
GET  /api/cron                               Authorization: Bearer <CRON_SECRET>
```

`/api/<route>` path style also works.

## Project structure

```text
app.py                 Flask entry point (WSGI `app`); serves public/ locally
flowtime/api.py        All API routes, authorization, cron endpoint
flowtime/core.py       Validation helpers
flowtime/db.py         Supabase REST + Auth token verification
flowtime/planner.py    Scheduler (Python port of public/planner.mjs; keep in sync)
flowtime/ai.py         OpenAI Responses API call + output validation
flowtime/mail.py       Resend handoff email + daily digest
public/                Browser UI (index.html, app.js, planner.mjs, demo.mjs, style.css)
supabase/schema.sql    Tables, RLS, transaction functions (run once on a new project)
tests/                 pytest suite; tests/frontend/ = optional Node tests for browser modules
vercel.json            Vercel function settings, security headers, daily cron
render.yaml            Optional Render deployment (gunicorn)
.github/workflows/     Optional GitHub Actions daily digest for hosts without cron
```

## Migrating an existing 2.x deployment

- **Database:** run `supabase/migrations/001_public_requests.sql`, then `002_decline_status.sql` (manager can decline/reopen requests). Both only add things, change no existing data, and are safe to re-run. Do **not** re-run `schema.sql` on a live database.
- **Vercel project settings:** the old guide set Framework Preset *Other*, Build Command `npm run build`, and Output Directory `public`. Change the Framework Preset to **Flask** and clear the Build Command and Output Directory overrides, then redeploy. Environment variables stay the same.
- The old Node files (`server.mjs`, `api/*.js`, `lib/`, `package.json`) were removed. Having `package.json` or `api/*.js` in the repo would make Vercel deploy Node functions again.

## Known limits

- One manager and many requesters. Collaborators are a text field, not separate accounts.
- Documents are links; there is no file upload. Busy periods are entered manually (no calendar sync).
- The scheduler works in 15-minute steps, up to 90 days ahead, and only plans accepted tasks.
- The timer keeps running when the app is closed, until the manager pauses it.
- The deadline digest runs once a day (00:00 UTC = 07:00 Vietnam). On Vercel's Hobby plan it can run any time within that hour.
- Each dataset is capped at 10,000 rows per request until server-side pagination is added.
- The session token is kept in tab `sessionStorage`, not in an HttpOnly cookie.
