"""Server-side port of public/planner.mjs. Keep both files in sync: the browser draws the
roadmap with planner.mjs, while the server uses this module for AI workload context.

Times are epoch milliseconds, like JavaScript Date.now().
"""

import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .core import to_ms

DEFAULT_SETTINGS = {
    "timezone": "Asia/Ho_Chi_Minh",
    "weekdays": [1, 2, 3, 4, 5],
    "start": 9,
    "end": 18,
    "lunchStart": 12,
    "lunchEnd": 13,
    "buffer": 15,
    "busy": [],
}

SLOT_MS = 900_000  # 15 minutes
DAY_MS = 86_400_000


def now_ms():
    return time.time() * 1000


def actual_minutes(task_id, sessions, now=None):
    now = now_ms() if now is None else now
    total = 0.0
    for s in sessions:
        if s.get("task_id") != task_id:
            continue
        end = to_ms(s["ended_at"]) if s.get("ended_at") else now
        total += max(0.0, (end - to_ms(s["started_at"])) / 60000)
    return total


def local_parts(ms, tz):
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(ZoneInfo(tz))
    return {
        "day": dt.strftime("%Y-%m-%d"),
        "weekday": dt.isoweekday() % 7,  # JavaScript convention: Sunday = 0
        "minute": dt.hour * 60 + dt.minute,
    }


def _busy_ranges(settings):
    return [(to_ms(b["start"]), to_ms(b["end"])) for b in settings.get("busy") or []]


def available(ms, settings, busy=None):
    busy = _busy_ranges(settings) if busy is None else busy
    p = local_parts(ms, settings["timezone"])
    m = p["minute"]
    return (
        p["weekday"] in settings["weekdays"]
        and settings["start"] * 60 <= m < settings["end"] * 60
        and not (settings["lunchStart"] * 60 <= m < settings["lunchEnd"] * 60)
        and not any(start <= ms < end for start, end in busy)
    )


def _deadline(task):
    return to_ms(task.get("committed_deadline") or task["requested_deadline"])


def schedule(tasks, plans, sessions, settings=None, now=None):
    """Quarter-hour slots; capacity respects working days, lunch, busy periods and buffer.
    Deterministic: AI cannot silently move accepted deadlines."""
    settings = settings or DEFAULT_SETTINGS
    now = now_ms() if now is None else now
    busy = _busy_ranges(settings)
    cursor = math.ceil(now / SLOT_MS) * SLOT_MS
    horizon = cursor + 90 * DAY_MS

    queue = []
    for t in tasks:
        if t.get("status") not in ("accepted", "doing"):
            continue
        plan = next((p for p in plans if p.get("task_id") == t["id"]), None)
        if plan:
            queue.append((t, plan))
    queue.sort(key=lambda x: (0 if x[0]["status"] == "doing" else 1, -x[1]["priority"], _deadline(x[0])))

    result = []
    for t, plan in queue:
        remaining = max(0.0, float(plan["estimate_minutes"]) - actual_minutes(t["id"], sessions, now))
        needed = remaining + (settings["buffer"] if remaining > 0 else 0)
        segments, first = [], None
        while needed > 0 and cursor < horizon:
            used = min(15, needed)
            slot_end = cursor + used * 60000
            if (
                available(cursor, settings, busy)
                and available(slot_end - 1, settings, busy)
                and not any(cursor < end and slot_end > start for start, end in busy)
            ):
                if first is None:
                    first = cursor
                if segments and segments[-1]["end"] == cursor:
                    segments[-1]["end"] = slot_end
                else:
                    segments.append({"start": cursor, "end": slot_end})
                needed -= used
            cursor += SLOT_MS
        finish = segments[-1]["end"] if segments else now
        result.append({
            "task": t,
            "remaining": remaining,
            "start": first,
            "end": finish,
            "segments": segments,
            "unscheduled": needed > 0,
            "risk": needed > 0 or finish > _deadline(t),
        })
    return result
