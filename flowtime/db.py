"""Supabase access. All table access uses the server-only service-role key; the browser never talks to tables."""

import json
import logging
import os

from . import http
from .core import HttpError, need

log = logging.getLogger("flowtime")


def configured():
    return all(
        os.environ.get(k)
        for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "FLOWTIME_MANAGER_ID")
    )


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
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        **(headers or {}),
    }
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
    """Verify the bearer token with Supabase Auth. Manager role comes ONLY from FLOWTIME_MANAGER_ID."""
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
        "manager": u["id"] == os.environ["FLOWTIME_MANAGER_ID"],
    }


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
