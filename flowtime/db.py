"""Supabase access. All table access uses the server-only service-role key; the browser never talks to tables."""

import json
import logging
import os

from . import http
from .core import HttpError, need

log = logging.getLogger("flowtime")


def configured():
    return all(os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"))


def _json(response):
    try:
        return response.json()
    except ValueError:
        return None


def db(path, method="GET", body=None, headers=None):
    need(configured(), 503, "Chưa cấu hình Supabase và tài khoản quản lý.")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    h = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        **(headers or {}),
    }
    # Legacy service_role keys are JWTs and are also sent as Bearer. New-style secret keys
    # (sb_secret_...) are not JWTs: Supabase wants them ONLY in the apikey header.
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    r = http.send(
        method,
        f"{os.environ['SUPABASE_URL']}/rest/v1/{path}",
        headers=h,
        data=None if body is None else json.dumps(body),
        timeout=12,
    )
    data = _json(r)
    if not r.ok:
        log.error("Database operation failed %s %s", r.status_code, (data or {}).get("code") if isinstance(data, dict) else None)
        if r.status_code == 409:
            raise HttpError(409, "Dữ liệu đã thay đổi. Hãy tải lại.")
        raise HttpError(500, "Không thể lưu/đọc dữ liệu. Kiểm tra schema và kết nối.")
    return data


def all_rows(path):
    result = []
    for start in range(0, 10000, 1000):
        rows = db(path, headers={"Range": f"{start}-{start + 999}", "Range-Unit": "items"}) or []
        result.extend(rows)
        if len(rows) < 1000:
            return result
    raise HttpError(413, "Dữ liệu quá lớn cho bản này. Cần thêm phân trang trước khi tiếp tục.")


def auth_user(authorization):
    """Verify the bearer token with Supabase Auth. Every confirmed account is a manager of its OWN
    workspace; access to any task is decided by tasks.manager_id, never by metadata from the browser."""
    need(configured(), 503, "Chưa cấu hình chế độ dùng thật.")
    need(isinstance(authorization, str) and authorization.startswith("Bearer "), 401, "Hãy đăng nhập.")
    r = http.send(
        "GET",
        f"{os.environ['SUPABASE_URL']}/auth/v1/user",
        headers={"apikey": os.environ["SUPABASE_ANON_KEY"], "Authorization": authorization},
        timeout=10,
    )
    need(r.ok, 401, "Phiên đăng nhập hết hạn. Hãy đăng nhập lại.")
    u = _json(r) or {}
    need(u.get("id") and u.get("email_confirmed_at"), 401, "Hãy xác nhận email trước khi sử dụng.")
    meta = u.get("user_metadata") or {}
    return {
        "id": u["id"],
        "email": u.get("email"),
        "name": meta.get("name") or u.get("email"),
        "manager": True,
    }


def ensure_manager(user):
    """Return the manager profile {slug, name}, creating it with a unique code on first sign-in."""
    import secrets
    from .core import RESERVED_SLUGS, slugify

    rows = db(f"managers?user_id=eq.{user['id']}&select=slug,name") or []
    if rows:
        return rows[0]
    base = slugify(user.get("name")) or slugify((user.get("email") or "").split("@")[0])
    if len(base) < 3 or base in RESERVED_SLUGS:
        base = (base + "-ql").strip("-") if base else "quan-ly"
    for attempt in range(6):
        slug = base if attempt == 0 else f"{base[:34]}-{secrets.randbelow(9000) + 1000}"
        try:
            created = db("managers", method="POST", body={
                "user_id": user["id"], "slug": slug, "name": user.get("name") or "", "email": user.get("email") or "",
            })
            return {"slug": created[0]["slug"], "name": created[0]["name"]}
        except HttpError as e:
            if e.status != 409:
                raise
            rows = db(f"managers?user_id=eq.{user['id']}&select=slug,name") or []
            if rows:  # created concurrently by another request
                return rows[0]
    raise HttpError(409, "Không tạo được mã người quản lý. Hãy thử lại.")


def global_quota(kind, limit):
    """Overall daily cap across all accounts (e.g. total AI calls), so open sign-up cannot run up costs."""
    allowed = db("rpc/consume_guest_quota", method="POST", body={"p_key": "all", "p_kind": kind, "p_limit": limit})
    need(allowed is True, 429, "Hệ thống đã đạt giới hạn sử dụng AI hôm nay. Vui lòng thử lại vào ngày mai.")


def quota(user, kind, limit):
    allowed = db("rpc/consume_quota", method="POST", body={"p_user": user["id"], "p_kind": kind, "p_limit": limit})
    need(allowed is True, 429, "Đã đạt giới hạn sử dụng hôm nay. Vui lòng thử vào ngày mai.")


def guest_quota(client_key, kind, per_client, overall):
    """Daily limits for anonymous use: per visitor and a global cap (bounds abuse even if IPs rotate)."""
    for key, limit in ((client_key, per_client), ("all", overall)):
        allowed = db("rpc/consume_guest_quota", method="POST", body={"p_key": key, "p_kind": kind, "p_limit": limit})
        need(allowed is True, 429, "Đã đạt giới hạn sử dụng hôm nay. Vui lòng thử lại vào ngày mai.")


def event(task, user, body):
    return db("events", method="POST", body={"task_id": task["id"], "actor_id": user["id"], "actor_name": user["name"], "body": body})
