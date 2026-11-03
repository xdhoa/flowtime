"""Python planner must behave like public/planner.mjs (ported from tests/frontend/planner.test.mjs)."""

from flowtime.core import to_ms
from flowtime.planner import DEFAULT_SETTINGS, actual_minutes, available, local_parts, schedule

SETTINGS = {**DEFAULT_SETTINGS, "buffer": 0, "busy": []}


def t(task_id, deadline, status="accepted"):
    return {"id": task_id, "title": task_id, "status": status, "requested_deadline": deadline}


def p(task_id, minutes=60, priority=2):
    return {"task_id": task_id, "estimate_minutes": minutes, "priority": priority}


def test_timer_elapsed_with_pause_and_open_session():
    sessions = [{"task_id": "a", "started_at": "2026-11-02T02:00Z", "ended_at": "2026-11-02T02:30Z"},
                {"task_id": "a", "started_at": "2026-11-02T03:00Z", "ended_at": None}]
    assert actual_minutes("a", sessions, to_ms("2026-11-02T03:15Z")) == 45


def test_planner_respects_lunch_weekend_and_timezone():
    now = to_ms("2026-11-06T04:30:00Z")
    r = schedule([t("a", "2026-11-10T00:00Z")], [p("a", 420)], [], SETTINGS, now)[0]
    assert r["segments"][0]["start"] == now
    assert r["segments"][0]["end"] == to_ms("2026-11-06T05:00Z")
    assert any(local_parts(s["start"], SETTINGS["timezone"])["weekday"] == 1 for s in r["segments"])
    assert all(available(s["start"], SETTINGS) for s in r["segments"])


def test_partial_slot_meetings_never_overlap_work():
    busy = {**SETTINGS, "busy": [{"start": "2026-11-02T02:05:00Z", "end": "2026-11-02T02:10:00Z"}]}
    r = schedule([t("a", "2026-11-03T00:00Z")], [p("a", 30)], [], busy, to_ms("2026-11-02T02:00Z"))[0]
    assert r["start"] == to_ms("2026-11-02T02:15Z")


def test_overflow_flags_risk_and_excludes_waiting_and_new():
    r = schedule([t("a", "2026-11-02T02:30Z"), t("b", "2026-11-03T00:00Z", "waiting"), t("c", "2026-11-03T00:00Z", "new")],
                 [p("a", 90), p("b"), p("c")], [], SETTINGS, to_ms("2026-11-02T02:00Z"))
    assert len(r) == 1 and r[0]["risk"] is True


def test_running_task_first_then_priority_then_deadline():
    r = schedule([t("a", "2026-11-02T12:00Z"), t("b", "2026-11-03T12:00Z"), t("c", "2026-11-04T12:00Z", "doing")],
                 [p("a", 30, 1), p("b", 30, 3), p("c", 30, 1)], [], SETTINGS, to_ms("2026-11-02T02:00Z"))
    assert [x["task"]["id"] for x in r] == ["c", "b", "a"]


def test_remaining_subtracts_actual_and_buffer_uses_working_slots():
    r = schedule([t("a", "2026-11-03T12:00Z")], [p("a", 60)],
                 [{"task_id": "a", "started_at": "2026-11-02T01:00Z", "ended_at": "2026-11-02T01:20Z"}],
                 {**SETTINGS, "buffer": 15}, to_ms("2026-11-02T02:00Z"))[0]
    assert r["remaining"] == 40
    assert (r["end"] - r["start"]) / 60000 == 55


def test_horizon_reports_unallocated_work():
    r = schedule([t("a", "2026-11-03T12:00Z")], [p("a", 100000)], [], SETTINGS, to_ms("2026-11-02T02:00Z"))[0]
    assert r["unscheduled"] is True and r["risk"] is True
