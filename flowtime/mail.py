"""Resend email: explicit manager handoff and the daily deadline digest. Idempotent per key."""

import hashlib
import json
import os
import time
from datetime import datetime, timezone

from . import http
from .core import HttpError, need, to_ms, vi_datetime
from .db import db


def send_mail(key, to, subject, body):
    need(
        os.environ.get("RESEND_API_KEY") and os.environ.get("EMAIL_FROM"),
        503,
        "Chưa cấu hình email. Bạn có thể sao chép nội dung hoặc dùng ứng dụng email.",
    )
    digest_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if db(f"mail_log?key=eq.{digest_key}&select=provider_id"):
        return {"sent": True, "duplicate": True}
    try:
        r = http.send(
            "POST",
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                "Content-Type": "application/json",
                "Idempotency-Key": digest_key,
            },
            data=json.dumps({"from": os.environ["EMAIL_FROM"], "to": [to], "subject": subject, "text": body}),
            timeout=15,
        )
        ok = r.ok
        response = r.json() if ok else None
    except Exception:
        ok, response = False, None
    if not ok:
        raise HttpError(502, "Chưa gửi được email. Kiểm tra cấu hình tên miền và email người nhận.")
    db(
        "mail_log?on_conflict=key",
        method="POST",
        body={"key": digest_key, "provider_id": (response or {}).get("id")},
        headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
    )
    return {"sent": True}


def digest():
    """Daily email to the manager: overdue work and work due within 24 hours."""
    need(os.environ.get("MANAGER_EMAIL"), 503, "Chưa có MANAGER_EMAIL.")
    now = time.time() * 1000
    limit = now + 86_400_000
    tasks = db(
        "tasks?status=not.in.(review,delivered)&requested_deadline=not.is.null"
        "&select=id,title,requested_deadline,committed_deadline,status&order=requested_deadline.asc&limit=1000"
    ) or []
    due = [t for t in tasks if to_ms(t.get("committed_deadline") or t["requested_deadline"]) <= limit]
    if not due:
        return {"sent": False, "count": 0}
    lines = []
    for t in due:
        deadline = t.get("committed_deadline") or t["requested_deadline"]
        label = "QUÁ HẠN" if to_ms(deadline) < now else "SẮP HẠN"
        lines.append(f"{label}: {t['title']} — {vi_datetime(deadline)}")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = send_mail(
        key="digest:" + today,
        to=os.environ["MANAGER_EMAIL"],
        subject=f"Flowtime: {len(due)} công việc cần chú ý",
        body="\n".join(lines) + "\n\nMở dashboard: " + os.environ.get("APP_URL", ""),
    )
    return {**result, "count": len(due)}
