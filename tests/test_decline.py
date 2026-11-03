"""Manager can decline a request (with a reason the requester sees) and reopen it."""

from conftest import TASK_ID


def test_requester_cannot_decline_or_reopen(call):
    assert call(f"tasks/{TASK_ID}/decline", method="POST", body={"reason": "x"})[0] == 403
    assert call(f"tasks/{TASK_ID}/reopen", method="POST", body={})[0] == 403


def test_decline_requires_sign_in(client, backend):
    r = client.post(f"/api/index?route=tasks/{TASK_ID}/decline", json={"reason": "x"})
    assert r.status_code == 401


def test_manager_declines_with_reason(call, backend):
    status, _ = call(f"tasks/{TASK_ID}/decline", method="POST", mode="manager", body={"reason": "Ngoài phạm vi"})
    assert status == 200
    assert backend.hit("/rpc/task_decline")[-1]["body"]["p_task"] == TASK_ID
    assert backend.hit("/events")[-1]["body"]["body"] == "Đã từ chối yêu cầu. Lý do: Ngoài phạm vi"


def test_decline_needs_reason(call):
    assert call(f"tasks/{TASK_ID}/decline", method="POST", mode="manager", body={"reason": "  "})[0] == 400


def test_cannot_decline_finished_work(call, backend):
    for status in ("delivered", "declined"):
        backend.task_status = status
        assert call(f"tasks/{TASK_ID}/decline", method="POST", mode="manager", body={"reason": "x"})[0] == 409


def test_reopen_only_declined(call, backend):
    backend.task_status = "accepted"
    assert call(f"tasks/{TASK_ID}/reopen", method="POST", mode="manager", body={})[0] == 409
    backend.task_status = "declined"
    assert call(f"tasks/{TASK_ID}/reopen", method="POST", mode="manager", body={})[0] == 200
    patch = [r for r in backend.hit("/tasks") if r["method"] == "PATCH"][-1]
    assert patch["body"]["status"] == "new"


def test_declined_not_scheduled():
    from flowtime.planner import DEFAULT_SETTINGS, schedule
    tasks = [{"id": "a", "title": "a", "status": "declined", "requested_deadline": "2026-11-05T10:00Z"}]
    assert schedule(tasks, [{"task_id": "a", "estimate_minutes": 60, "priority": 2}], [], DEFAULT_SETTINGS) == []
