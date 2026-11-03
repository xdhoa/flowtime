"""Input validation and HTTP error helpers shared by all endpoints."""

import math
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def need(value, status, message):
    if not value:
        raise HttpError(status, message)


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def is_uuid(value):
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def text(value, max_len=4000, required=False):
    need(isinstance(value, str), 400, "Thông tin phải là văn bản.")
    v = value.strip()
    need(len(v) <= max_len and (not required or len(v) > 0), 400, "Nội dung trống hoặc quá dài.")
    return v


def parse_datetime(value):
    """Parse an ISO 8601 string to an aware UTC datetime. Naive values are treated as UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """Same shape as JavaScript Date.toISOString(): 2026-11-05T10:00:00.000Z."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_ms(value):
    return parse_datetime(value).timestamp() * 1000


def timestamp(value):
    try:
        return to_iso(parse_datetime(value))
    except (TypeError, ValueError, OverflowError):
        raise HttpError(400, "Ngày giờ không hợp lệ.")


def number(value, minimum, maximum):
    ok = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and minimum <= value <= maximum
    )
    need(ok, 400, "Giá trị số không hợp lệ.")
    return value


def is_integer(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and float(value).is_integer()


def safe_url(value):
    v = text(value, 2000)
    if not v:
        return ""
    try:
        parts = urlsplit(v)
    except ValueError:
        raise HttpError(400, "Đường dẫn không hợp lệ.")
    need(parts.scheme.lower() in ("http", "https"), 400, "Chỉ nhận đường dẫn http/https.")
    need(parts.netloc and not any(c.isspace() for c in v), 400, "Đường dẫn không hợp lệ.")
    return v


def request_fields(b):
    """Only whitelisted, validated fields reach the database; identity/status are set by the server."""
    return {
        "title": text(b.get("title"), 250, True),
        "description": text(b.get("description") or "", 6000),
        "deliverable": text(b.get("deliverable") or "", 2000),
        "collaborators": text(b.get("collaborators") or "", 500),
        "requested_deadline": timestamp(b.get("requested_deadline")),
        "category": text(b.get("category") or "Khác", 80),
        "attachment_url": safe_url(b.get("attachment_url") or ""),
    }


def visible_task(user, task):
    return user["manager"] or task.get("requester_id") == user["id"]


def manager_only(user):
    need(user["manager"], 403, "Chỉ tài khoản quản lý có quyền thực hiện.")


def valid_timezone(name):
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def validate_settings(b):
    v = {
        "timezone": text(b.get("timezone"), 80, True),
        "weekdays": b.get("weekdays"),
        "start": number(b.get("start"), 0, 23.75),
        "end": number(b.get("end"), 0.25, 24),
        "lunchStart": number(b.get("lunchStart"), 0, 24),
        "lunchEnd": number(b.get("lunchEnd"), 0, 24),
        "buffer": number(b.get("buffer"), 0, 120),
        "busy": b.get("busy") or [],
    }
    need(valid_timezone(v["timezone"]), 400, "Múi giờ không hợp lệ.")
    need(v["start"] < v["end"] and v["lunchStart"] <= v["lunchEnd"], 400, "Khoảng giờ không hợp lệ.")
    weekdays = v["weekdays"]
    need(
        isinstance(weekdays, list) and weekdays and all(is_integer(n) and 0 <= n <= 6 for n in weekdays),
        400,
        "Chọn ít nhất một ngày làm việc.",
    )
    v["weekdays"] = [int(n) for n in weekdays]
    need(isinstance(v["busy"], list) and len(v["busy"]) <= 200, 400, "Tối đa 200 khoảng bận.")
    busy = []
    for item in v["busy"]:
        need(isinstance(item, dict), 400, "Khoảng bận không hợp lệ.")
        start, end = timestamp(item.get("start")), timestamp(item.get("end"))
        need(start < end, 400, "Giờ kết thúc phải sau giờ bắt đầu.")
        busy.append({"start": start, "end": end, "label": text(item.get("label") or "Bận", 120)})
    v["busy"] = busy
    return v


def vi_datetime(value, tz="Asia/Ho_Chi_Minh"):
    """Matches JS toLocaleString('vi-VN'): '17:00:00 7/11/2026'."""
    dt = parse_datetime(value).astimezone(ZoneInfo(tz))
    return f"{dt:%H:%M:%S} {dt.day}/{dt.month}/{dt.year}"
