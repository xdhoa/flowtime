"""API authorization and contract tests (ported from tests/api.test.mjs, plus extra cases)."""

import pytest

from conftest import MANAGER, OTHER, REQUESTER, TASK_ID
from flowtime import http
from flowtime.ai import ask_ai
from flowtime.core import HttpError


def test_data_is_scoped_to_own_workspace(call, backend):
    status, data = call("data", mode="other-manager")
    assert status == 200
    assert data["manager"] == {"slug": "hoa", "name": "Hòa"}
    # Every read is filtered to the signed-in account; nothing is fetched unfiltered.
    assert all(r["query"].get("manager_id") == ["eq." + OTHER] for r in backend.hit("/tasks"))
    assert all(r["query"].get("manager_id") == ["eq." + OTHER] for r in backend.hit("/sessions"))
    assert all(r["query"].get("tasks.manager_id") == ["eq." + OTHER] for r in backend.hit("/plans"))


def test_first_sign_in_creates_manager_code(call, backend):
    backend.has_profile = False
    status, data = call("data", mode="manager")
    assert status == 200
    created = [r for r in backend.hit("/managers") if r["method"] == "POST"][-1]["body"]
    assert created["slug"] == "ngoc-hoa" and created["user_id"] == MANAGER
    assert data["manager"]["slug"] == "ngoc-hoa"


def test_change_code(call, backend):
    assert call("profile", method="POST", mode="manager", body={"slug": "hoa-2026"})[0] == 200
    assert call("profile", method="POST", mode="manager", body={"slug": "taken"})[0] == 409
    # Upper case is accepted and stored lower case.
    status, data = call("profile", method="POST", mode="manager", body={"slug": "Hoa-Team"})
    assert status == 200 and data["slug"] == "hoa-team"
    for bad in ("ab", "hòa", "-hoa", "hoa team", "login", "a" * 41):
        assert call("profile", method="POST", mode="manager", body={"slug": bad})[0] == 400


@pytest.mark.parametrize("route", [f"tasks/{TASK_ID}/plan", f"tasks/{TASK_ID}/timer", f"tasks/{TASK_ID}/status",
                                   f"tasks/{TASK_ID}/decline", f"tasks/{TASK_ID}/comment", f"tasks/{TASK_ID}/events"])
def test_other_manager_cannot_touch_my_task(call, route):
    status, _ = call(route, method="GET" if route.endswith("events") else "POST", mode="other-manager", body=None if route.endswith("events") else {})
    assert status == 404


def test_other_manager_cannot_estimate_my_task(call, backend, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    status, _ = call("ai", method="POST", mode="other-manager", body={"mode": "estimate", "task_id": TASK_ID})
    assert status == 404


def test_manager_receives_private_plan_data(call):
    status, data = call("data", mode="manager")
    assert status == 200
    assert data["user"]["manager"] is True
    assert data["plans"][0]["private_notes"] == "PRIVATE"


def test_requester_cannot_access_another_users_task(call):
    status, _ = call(f"tasks/{TASK_ID}/events", mode="other-task")
    assert status == 404


@pytest.mark.parametrize("route", [f"tasks/{TASK_ID}/plan", f"tasks/{TASK_ID}/timer", f"tasks/{TASK_ID}/status",
                                   f"tasks/{TASK_ID}/handoff"])
def test_signed_in_sender_cannot_manage_the_task(call, route):
    # The sender can see the task (requester_id) but only the owning manager may change it.
    status, _ = call(route, method="POST", body={})
    assert status == 403


def test_task_creation_binds_identity_and_ignores_injected_fields(call):
    status, data = call("tasks", method="POST", body={
        "title": "Test", "requested_deadline": "2026-11-05T10:00Z",
        "requester_id": OTHER, "manager_id": OTHER, "status": "delivered", "private_notes": "x",
    })
    assert status == 201
    task = data["task"]
    assert task["requester_id"] == REQUESTER and task["manager_id"] == REQUESTER
    assert task["status"] == "new"
    assert "private_notes" not in task
    assert task["requested_deadline"] == "2026-11-05T10:00:00.000Z"


def test_cross_origin_mutation_is_blocked(call):
    status, _ = call("tasks", method="POST", body={}, origin="https://malicious.example")
    assert status == 403


def test_same_origin_mutation_is_allowed(call):
    status, _ = call("tasks", method="POST", origin="https://flowtime.example",
                     body={"title": "T", "requested_deadline": "2026-11-05T10:00Z"})
    assert status == 201


def test_invalid_json_and_non_object_bodies_are_rejected(call):
    assert call("tasks", method="POST", raw="{not json")[0] == 400
    assert call("tasks", method="POST", raw="[1,2]")[0] == 400


def test_oversized_body_is_rejected(call):
    status, _ = call("tasks", method="POST", raw='{"title":"' + "x" * 41000 + '"}')
    assert status == 413


def test_ai_missing_key_gives_clear_configuration_error(call):
    status, data = call("ai", method="POST", body={"mode": "parse", "message": "Create proposal"})
    assert status == 503
    assert "OPENAI_API_KEY" in data["error"]


def test_config_never_exposes_secrets(call):
    status, data = call("config")
    assert status == 200
    assert "secret-test-key" not in str(data)


def test_missing_token_is_401(client, backend):
    r = client.get("/api/index?route=data")
    assert r.status_code == 401


def test_path_style_routes_still_work(client, backend):
    r = client.get("/api/config")
    assert r.status_code == 200 and r.get_json()["configured"] is True


def test_requester_can_only_accept_results_in_review(call, backend):
    backend.task_status = "accepted"
    assert call(f"tasks/{TASK_ID}/accept", method="POST", body={})[0] == 403
    backend.task_status = "review"
    assert call(f"tasks/{TASK_ID}/accept", method="POST", body={})[0] == 200
    patch = [r for r in backend.hit("/tasks") if r["method"] == "PATCH"][-1]
    assert patch["body"]["status"] == "delivered"


def test_manager_plan_sets_committed_deadline_and_accepts(call, backend):
    status, _ = call(f"tasks/{TASK_ID}/plan", method="POST", mode="manager", body={
        "estimate_minutes": 60, "priority": 2, "committed_deadline": "2026-11-07T10:00:00.000Z", "private_notes": "n"})
    assert status == 200
    patch = [r for r in backend.hit("/tasks") if r["method"] == "PATCH"][-1]
    assert patch["body"]["status"] == "accepted"
    assert patch["body"]["committed_deadline"] == "2026-11-07T10:00:00.000Z"
    event = backend.hit("/events")[-1]["body"]["body"]
    assert event == "Đã xác nhận lịch bàn giao: 17:00:00 7/11/2026."


def test_manager_plan_rejects_bad_priority(call):
    status, _ = call(f"tasks/{TASK_ID}/plan", method="POST", mode="manager", body={
        "estimate_minutes": 60, "priority": 1.5, "committed_deadline": "2026-11-07T10:00Z"})
    assert status == 400


def test_review_status_requires_result(call, backend):
    status, _ = call(f"tasks/{TASK_ID}/status", method="POST", mode="manager", body={"status": "review", "result": " "})
    assert status == 400
    status, _ = call(f"tasks/{TASK_ID}/status", method="POST", mode="manager", body={"status": "review", "result": "Link"})
    assert status == 200
    assert backend.hit("/rpc/task_status")[-1]["body"]["p_status"] == "review"


def test_cron_fails_closed_without_secret(client, backend):
    assert client.get("/api/cron").status_code == 401


def test_cron_rejects_wrong_secret(client, backend, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "x" * 40)
    assert client.get("/api/cron", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_cron_with_secret_and_nothing_due(client, backend, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "x" * 40)
    monkeypatch.setenv("MANAGER_EMAIL", "m@example.com")
    backend.task_status = "accepted"
    # Fake task deadline (2026-11-05) may be due relative to today's date; either outcome must be a clean JSON reply.
    r = client.get("/api/cron", headers={"Authorization": "Bearer " + "x" * 40})
    assert r.status_code in (200, 503)
    assert isinstance(r.get_json(), dict)


def test_ai_refusal_never_becomes_an_estimate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")

    class Refusal:
        ok, status_code = True, 200

        def json(self):
            return {"status": "completed", "output": [{"content": [{"type": "refusal", "refusal": "No"}]}]}

    monkeypatch.setattr(http, "send", lambda *a, **k: Refusal())
    with pytest.raises(HttpError) as e:
        ask_ai("estimate", {})
    assert e.value.status == 502


def test_ai_malformed_numbers_are_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")

    class Bad:
        ok, status_code = True, 200

        def json(self):
            return {"status": "completed", "output": [{"content": [{"type": "output_text",
                    "text": '{"message":"m","low_minutes":90,"high_minutes":30,"steps":[]}'}]}]}

    monkeypatch.setattr(http, "send", lambda *a, **k: Bad())
    with pytest.raises(HttpError):
        ask_ai("estimate", {})
