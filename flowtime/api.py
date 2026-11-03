"""JSON API (contract used by public/app.js and public/guest.mjs):

    GET  /api/index?route=config | data | tasks/<id>/events
    POST /api/index?route=tasks | settings | profile | ai | auth/<op> | tasks/<id>/<action>
    POST /api/index?route=public/manager | public/tasks | public/track | public/comment | public/accept | public/ai
    GET  /api/cron  (Authorization: Bearer <CRON_SECRET>)

Multi-manager model: every confirmed account is a manager with a private workspace and a public
request code (slug). Requesters need no account: they submit through a manager's link
(#request/<slug>) and follow their request with a secret tracking token.
Every signed-in route verifies the token on the server, and every task action checks that the task
belongs to the signed-in manager (tasks.manager_id).
"""

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from . import VERSION, http
from .ai import ask_ai
from .core import (
    HttpError, is_uuid, need, number, owner_only, owns, request_fields, text, timestamp,
    to_iso, valid_slug, validate_settings, vi_datetime, visible_task,
)
from .db import all_rows, auth_user, configured, db, ensure_manager, event, global_quota, guest_quota, quota
from .mail import digest, send_mail
from .planner import DEFAULT_SETTINGS, actual_minutes, schedule

log = logging.getLogger("flowtime")
bp = Blueprint("api", __name__)

MAX_BODY = 40_000
STATUS_LABELS = {"accepted": "Đã tiếp nhận", "waiting": "Chờ phối hợp", "review": "Chờ duyệt", "delivered": "Đã bàn giao"}
TASK_ROUTE = re.compile(r"^tasks/([0-9a-f-]+)(?:/(events|plan|timer|status|comment|handoff|accept|decline|reopen))?$", re.I)


def ai_daily_limit():
    try:
        return max(1, int(os.environ.get("AI_DAILY_LIMIT") or 300))
    except ValueError:
        return 300


def reply(status, value):
    response = jsonify(value)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def now_iso():
    return to_iso(datetime.now(timezone.utc))


def read_body():
    raw = request.get_data(cache=False, as_text=True) or ""
    need(len(raw) < MAX_BODY, 413, "Yêu cầu quá lớn.")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        raise HttpError(400, "Dữ liệu JSON không hợp lệ.")
    need(isinstance(value, dict), 400, "Dữ liệu JSON không hợp lệ.")
    return value


def check_origin():
    """Block cross-site POSTs: Origin must be APP_URL or this host."""
    origin = request.headers.get("Origin")
    if not origin:
        return
    app_url = os.environ.get("APP_URL")
    expected = None
    if app_url:
        parts = urlsplit(app_url)
        expected = f"{parts.scheme}://{parts.netloc}"
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    host_origin = f"{proto}://{request.headers.get('Host', '')}"
    need(origin == expected or origin == host_origin, 403, "Nguồn yêu cầu không hợp lệ.")


@bp.route("/api/index", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@bp.route("/api/<path:path_route>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api(path_route=None):
    try:
        route = request.args.get("route") or (path_route or "").strip("/")
        return handle(route)
    except HttpError as e:
        return reply(e.status, {"error": e.message})
    except Exception as e:
        log.error("API error %s", type(e).__name__)
        return reply(500, {"error": "Có lỗi hệ thống. Vui lòng thử lại."})


def own_plans(user):
    """Plans have no manager column; filter through the parent task (PostgREST inner join)."""
    rows = all_rows(f"plans?select=*,tasks!inner(manager_id)&tasks.manager_id=eq.{user['id']}")
    return [{k: v for k, v in p.items() if k != "tasks"} for p in rows]


def own_workspace(user):
    tasks = all_rows(f"tasks?manager_id=eq.{user['id']}&order=created_at.desc")
    plans = own_plans(user)
    sessions = all_rows(f"sessions?manager_id=eq.{user['id']}")
    rows = db(f"settings?manager_id=eq.{user['id']}") or []
    settings = rows[0]["value"] if rows else DEFAULT_SETTINGS
    return tasks, plans, sessions, settings


def handle(route):
    method = request.method
    if method == "GET" and route == "config":
        return reply(200, {
            "configured": configured(),
            "ai": bool(os.environ.get("OPENAI_API_KEY")),
            "email": bool(os.environ.get("RESEND_API_KEY")),
            "appURL": os.environ.get("APP_URL", ""),
            "version": VERSION,
        })
    need(method in ("GET", "POST"), 405, "Phương thức không hỗ trợ.")
    if method == "POST":
        check_origin()
    b = read_body() if method == "POST" else {}
    if route.startswith("auth/"):
        return auth_route(route, b)
    if route.startswith("public/"):
        return public_route(route, b)

    user = auth_user(request.headers.get("Authorization"))

    if method == "GET" and route == "data":
        profile = ensure_manager(user)
        tasks, plans, sessions, settings = own_workspace(user)
        return reply(200, {
            "user": user, "manager": profile, "tasks": [strip_secret(t) for t in tasks],
            "plans": plans, "sessions": sessions, "settings": settings,
        })

    if method == "POST" and route == "profile":
        slug = valid_slug(b.get("slug"))
        ensure_manager(user)
        try:
            db(f"managers?user_id=eq.{user['id']}", method="PATCH", body={"slug": slug})
        except HttpError as e:
            if e.status == 409:
                raise HttpError(409, "Mã này đã có người dùng. Hãy chọn mã khác.")
            raise
        return reply(200, {"ok": True, "slug": slug})

    if method == "POST" and route == "tasks":
        # A manager adding work to their own list.
        quota(user, "requests", 50)
        fields = request_fields(b)
        created = db("tasks", method="POST", body={
            **fields,
            "manager_id": user["id"],
            "requester_id": user["id"],
            "requester_email": user["email"],
            "requester_name": user["name"],
            "status": "new",
        })
        task = strip_secret(created[0])
        event(task, user, "Đã gửi yêu cầu mới.")
        return reply(201, {"task": task})

    if method == "POST" and route == "settings":
        settings = validate_settings(b)
        db("settings?on_conflict=manager_id", method="POST", body={"manager_id": user["id"], "value": settings},
           headers={"Prefer": "resolution=merge-duplicates,return=representation"})
        return reply(200, {"ok": True})

    if method == "POST" and route == "ai":
        return ai_route(user, b)

    match = TASK_ROUTE.match(route)
    need(match and is_uuid(match.group(1)), 404, "Không tìm thấy đường dẫn.")
    task_id, action = match.group(1), match.group(2)
    rows = db(f"tasks?id=eq.{task_id}") or []
    task = rows[0] if rows else None
    # 404 (not 403) so other accounts cannot probe which task IDs exist.
    need(task and visible_task(user, task), 404, "Không tìm thấy công việc.")

    if method == "GET" and action == "events":
        return reply(200, {"events": all_rows(f"events?task_id=eq.{task['id']}&order=created_at.asc")})
    need(method == "POST", 405, "Phương thức không hỗ trợ.")

    if action == "comment":
        quota(user, "comments", 200)
        event(task, user, text(b.get("body"), 4000, True))
        return reply(200, {"ok": True})

    if action == "accept":
        need(task.get("requester_id") == user["id"] and task["status"] == "review", 403,
             "Chỉ người giao việc có thể duyệt kết quả đang chờ.")
        db(f"tasks?id=eq.{task['id']}&status=eq.review", method="PATCH", body={"status": "delivered", "updated_at": now_iso()})
        event(task, user, "Đã xác nhận kết quả và hoàn tất bàn giao.")
        return reply(200, {"ok": True})

    # Everything below changes the plan, time or status: only the owning manager.
    owner_only(user, task)

    if action == "plan":
        estimate = number(b.get("estimate_minutes"), 1, 100000)
        priority = number(b.get("priority"), 1, 3)
        need(float(priority).is_integer(), 400, "Ưu tiên không hợp lệ.")
        deadline = timestamp(b.get("committed_deadline"))
        # AI content is advisory; only this explicit manager submission writes the plan.
        ai = b.get("ai_estimate") or None
        need(not ai or len(json.dumps(ai)) < 20000, 400, "Kết quả AI quá dài.")
        db("plans?on_conflict=task_id", method="POST", body={
            "task_id": task["id"], "estimate_minutes": estimate, "priority": int(priority),
            "private_notes": text(b.get("private_notes") or "", 4000), "ai_estimate": ai,
        }, headers={"Prefer": "resolution=merge-duplicates,return=representation"})
        db(f"tasks?id=eq.{task['id']}", method="PATCH", body={
            "committed_deadline": deadline,
            "status": "accepted" if task["status"] == "new" else task["status"],
            "updated_at": now_iso(),
        })
        event(task, user, f"Đã xác nhận lịch bàn giao: {vi_datetime(deadline)}.")
        return reply(200, {"ok": True})

    if action == "timer":
        need(b.get("action") in ("start", "pause"), 400, "Thao tác không hợp lệ.")
        if b["action"] == "start":
            plans = db(f"plans?task_id=eq.{task['id']}") or []
            need(plans and task["status"] in ("accepted", "doing"), 409,
                 "Hãy tiếp nhận và xác nhận thời lượng trước khi bắt đầu.")
        # Atomic in PostgreSQL: one running timer per manager, only on that manager's own tasks.
        db("rpc/timer_change", method="POST", body={"p_manager": user["id"], "p_task": task["id"], "p_action": b["action"]})
        return reply(200, {"ok": True})

    if action == "status":
        status = b.get("status")
        need(status in STATUS_LABELS, 400, "Trạng thái không hợp lệ.")
        need(db(f"plans?task_id=eq.{task['id']}"), 409, "Hãy xác nhận kế hoạch trước.")
        result = text(b["result"] if b.get("result") is not None else task.get("result", ""), 6000)
        need(status not in ("review", "delivered") or result.strip(), 400, "Hãy nhập kết quả hoặc đường dẫn bàn giao.")
        db("rpc/task_status", method="POST", body={"p_manager": user["id"], "p_task": task["id"], "p_status": status, "p_result": result})
        event(task, user, f"Đã cập nhật trạng thái: {STATUS_LABELS[status]}.")
        return reply(200, {"ok": True})

    if action == "decline":
        need(task["status"] not in ("delivered", "declined"), 409, "Không thể từ chối việc đã bàn giao hoặc đã từ chối.")
        reason = text(b.get("reason"), 2000, True)
        db("rpc/task_decline", method="POST", body={"p_manager": user["id"], "p_task": task["id"]})
        event(task, user, f"Đã từ chối yêu cầu. Lý do: {reason}")
        return reply(200, {"ok": True})

    if action == "reopen":
        need(task["status"] == "declined", 409, "Chỉ mở lại được yêu cầu đã từ chối.")
        db(f"tasks?id=eq.{task['id']}&status=eq.declined", method="PATCH", body={"status": "new", "updated_at": now_iso()})
        event(task, user, "Đã mở lại yêu cầu để xem xét.")
        return reply(200, {"ok": True})

    if action == "handoff":
        need(task["status"] in ("review", "delivered"), 409, "Hãy hoàn thành và nhập kết quả trước khi gửi.")
        quota(user, "handoff", 50)
        message = text(b.get("body"), 8000, True)
        sent = send_mail(key=f"handoff:{task['id']}:{task.get('updated_at')}", to=task["requester_email"],
                         subject=f"Bàn giao: {task['title']}", body=message)
        if not sent.get("duplicate"):
            event(task, user, "Đã gửi email bàn giao cho người yêu cầu.")
        return reply(200, sent)

    raise HttpError(404, "Không tìm thấy thao tác.")


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{30,100}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# What a tracking-link holder may see: the shared brief, deadlines, status and result. Nothing internal.
PUBLIC_TASK_FIELDS = (
    "id", "title", "description", "deliverable", "category", "collaborators", "attachment_url",
    "requested_deadline", "committed_deadline", "status", "result", "requester_name", "created_at", "updated_at",
)
BAD_LINK = "Đường dẫn theo dõi không hợp lệ hoặc đã hết hiệu lực."
NO_MANAGER = "Không tìm thấy người quản lý với mã này. Hãy kiểm tra lại đường link hoặc mã."


def strip_secret(task):
    return {k: v for k, v in task.items() if k != "guest_token_hash"}


def token_hash(token):
    # Only the hash is stored, so a database leak does not reveal working tracking links.
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def client_key():
    """Best-effort visitor key for anonymous rate limits; the raw IP is never stored.
    X-Real-IP is set by Vercel; otherwise use the hop appended by the nearest proxy."""
    forwarded = [p.strip() for p in (request.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
    ip = request.headers.get("X-Real-IP") or (forwarded[-1] if forwarded else None) or request.remote_addr or "unknown"
    secret = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "flowtime").encode()
    return "v:" + hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()[:32]


def guest_task(b):
    token = b.get("token")
    need(isinstance(token, str) and TOKEN_RE.match(token), 404, BAD_LINK)
    rows = db(f"tasks?guest_token_hash=eq.{token_hash(token)}") or []
    need(rows, 404, BAD_LINK)
    return rows[0]


def find_manager(slug_value):
    slug = slug_value.strip().lower() if isinstance(slug_value, str) else ""
    need(re.match(r"^[a-z0-9-]{3,40}$", slug), 404, NO_MANAGER)
    rows = db(f"managers?slug=eq.{slug}&select=user_id,slug,name") or []
    need(rows, 404, NO_MANAGER)
    return rows[0]


def public_route(route, b):
    """No sign-in. Submitting creates a request for one manager plus a secret tracking token returned once."""
    need(request.method == "POST", 405, "Yêu cầu POST.")
    operation = route[len("public/"):]

    if operation == "manager":
        guest_quota(client_key(), "guest_lookup", 60, 5000)
        manager = find_manager(b.get("slug"))
        return reply(200, {"slug": manager["slug"], "name": manager["name"] or manager["slug"]})

    if operation == "tasks":
        # Honeypot: real people never see or fill this field.
        need(not b.get("website"), 400, "Không gửi được yêu cầu.")
        name = text(b.get("name"), 120, True)
        email = text(b.get("email"), 254, True)
        need(EMAIL_RE.match(email), 400, "Email không hợp lệ.")
        fields = request_fields(b)
        manager = find_manager(b.get("manager"))
        guest_quota(client_key(), "guest_requests", 10, 300)
        token = secrets.token_urlsafe(32)
        created = db("tasks", method="POST", body={
            **fields,
            "manager_id": manager["user_id"],
            "requester_id": None,
            "requester_email": email,
            "requester_name": name,
            "status": "new",
            "guest_token_hash": token_hash(token),
        })
        task = created[0]
        event(task, {"id": None, "name": name}, "Đã gửi yêu cầu mới (không đăng nhập).")
        return reply(201, {"task": {"id": task["id"], "title": task["title"]}, "token": token,
                           "manager": manager["name"] or manager["slug"]})

    if operation == "ai":
        guest_quota(client_key(), "guest_ai", 5, 100)
        payload = {
            "now": now_iso(),
            "timezone": text(b.get("timezone") or "Asia/Ho_Chi_Minh", 80),
            "conversation": text(b.get("message") or "", 8000),
            "mode": "parse",
        }
        return reply(200, {"analysis": ask_ai("parse", payload)})

    need(operation in ("track", "comment", "accept"), 404, "Không tìm thấy đường dẫn.")
    task = guest_task(b)
    guest = {"id": None, "name": task["requester_name"]}

    if operation == "track":
        return reply(200, {
            "task": {k: task.get(k) for k in PUBLIC_TASK_FIELDS},
            "events": all_rows(f"events?task_id=eq.{task['id']}&order=created_at.asc"),
        })

    if operation == "comment":
        guest_quota(client_key(), "guest_comments", 100, 2000)
        event(task, guest, text(b.get("body"), 4000, True))
        return reply(200, {"ok": True})

    # accept: the requester approves a result that is waiting for review.
    need(task["status"] == "review", 403, "Chỉ duyệt được kết quả đang chờ duyệt.")
    db(f"tasks?id=eq.{task['id']}&status=eq.review", method="PATCH", body={"status": "delivered", "updated_at": now_iso()})
    event(task, guest, "Đã xác nhận kết quả và hoàn tất bàn giao.")
    return reply(200, {"ok": True})


def ai_route(user, b):
    mode = b.get("mode")
    need(mode in ("parse", "estimate", "advice"), 400, "Chế độ AI không hợp lệ.")
    quota(user, "ai", 50)
    global_quota("ai_total", ai_daily_limit())
    payload = {
        "now": now_iso(),
        "timezone": text(b.get("timezone") or "Asia/Ho_Chi_Minh", 80),
        "conversation": text(b.get("message") or "", 8000),
        "mode": mode,
    }
    if mode != "parse":
        # Only this manager's own workspace is ever sent to the AI.
        tasks, plans, sessions, settings = own_workspace(user)
        plan_by_task = {p["task_id"]: p for p in plans}
        payload["history"] = [
            {
                "category": t.get("category"),
                "estimate": (plan_by_task.get(t["id"]) or {}).get("estimate_minutes"),
                "actual": round(actual_minutes(t["id"], sessions)),
            }
            for t in [t for t in tasks if t.get("status") == "delivered"][:50]
        ]
        payload["workload"] = [
            {
                "title": p["task"]["title"],
                "deadline": p["task"].get("committed_deadline") or p["task"]["requested_deadline"],
                "remaining": p["remaining"],
                "finish": to_iso(datetime.fromtimestamp(p["end"] / 1000, tz=timezone.utc)),
                "risk": p["risk"],
            }
            for p in schedule(tasks, plans, sessions, settings)
        ]
        payload["settings"] = settings
        if mode == "estimate":
            need(is_uuid(b.get("task_id")), 400, "Mã công việc không hợp lệ.")
            task = next((t for t in tasks if t["id"] == b["task_id"]), None)
            need(task and owns(user, task), 404, "Không tìm thấy công việc.")
            payload["task"] = {k: task.get(k) for k in ("title", "description", "deliverable", "category", "requested_deadline")}
    return reply(200, {"analysis": ask_ai(mode, payload)})


AUTH_OPERATIONS = ("login", "signup", "refresh", "recover", "logout", "password")


def auth_route(route, b):
    """Thin proxy to Supabase Auth so the browser needs no Supabase keys or SDK."""
    need(configured(), 503, "Chưa cấu hình Supabase.")
    operation = route[5:]
    need(operation in AUTH_OPERATIONS, 404, "Thao tác đăng nhập không hợp lệ.")
    need(request.method == "POST", 405, "Yêu cầu POST.")
    if operation in ("login", "signup"):
        email = text(b.get("email"), 254, True)
        need(EMAIL_RE.match(email), 400, "Email không hợp lệ.")
        password = text(b.get("password"), 128, True)
        need(len(password) >= 8, 400, "Mật khẩu cần ít nhất 8 ký tự.")
        path = "token?grant_type=password" if operation == "login" else "signup"
        payload = {"email": email, "password": password}
        if operation == "signup":
            # Only a display name goes into metadata; permissions never come from metadata.
            payload["data"] = {"name": text(b.get("name") or email, 120)}
    elif operation == "refresh":
        path, payload = "token?grant_type=refresh_token", {"refresh_token": text(b.get("refresh_token"), 4000, True)}
    elif operation == "recover":
        path, payload = "recover", {"email": text(b.get("email"), 254, True)}
    elif operation == "password":
        auth_user(request.headers.get("Authorization"))
        path, payload = "user", {"password": text(b.get("password"), 128, True)}
        need(len(payload["password"]) >= 8, 400, "Mật khẩu cần ít nhất 8 ký tự.")
    else:
        auth_user(request.headers.get("Authorization"))
        path, payload = "logout", {}

    headers = {"apikey": os.environ["SUPABASE_ANON_KEY"], "Content-Type": "application/json"}
    if request.headers.get("Authorization"):
        headers["Authorization"] = request.headers["Authorization"]
    r = http.send("PUT" if operation == "password" else "POST", f"{os.environ['SUPABASE_URL']}/auth/v1/{path}",
                  headers=headers, data=json.dumps(payload), timeout=12)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if not r.ok:
        raise HttpError(
            429 if r.status_code == 429 else 400,
            "Email/mật khẩu chưa đúng hoặc email chưa được xác nhận." if operation == "login"
            else "Chưa thực hiện được. Kiểm tra email, cấu hình Auth và thử lại.",
        )
    return reply(200, data if data is not None else {"ok": True})


@bp.route("/api/cron", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def cron():
    """Daily deadline digest to every manager. Fails closed when CRON_SECRET is missing."""
    secret = os.environ.get("CRON_SECRET") or ""
    expected = f"Bearer {secret}".encode()
    actual = (request.headers.get("Authorization") or "").encode()
    if request.method != "GET" or not secret or not hmac.compare_digest(actual, expected):
        return reply(401, {"error": "Unauthorized"})
    try:
        return reply(200, digest())
    except HttpError as e:
        return reply(e.status, {"error": e.message})
    except Exception as e:
        log.error("Cron error %s", type(e).__name__)
        return reply(500, {"error": "Không thể gửi nhắc hạn."})
