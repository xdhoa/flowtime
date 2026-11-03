"""No-sign-in request flow: anyone can submit; only the tracking-link holder can follow it;
only the signed-in manager can manage work."""

import pytest

from conftest import TASK_ID
from flowtime.api import token_hash

GOOD = {"name": "Lan", "email": "lan@example.com", "title": "Poster", "requested_deadline": "2026-11-05T10:00Z"}


def post(client, route, body, origin=None):
    headers = {"Host": "flowtime.example", "X-Forwarded-Proto": "https"}
    if origin:
        headers["Origin"] = origin
    r = client.post("/api/index?route=" + route, json=body, headers=headers)
    return r.status_code, r.get_json()


def test_guest_can_submit_without_signing_in(client, backend):
    status, data = post(client, "public/tasks", GOOD)
    assert status == 201
    token = data["token"]
    assert len(token) >= 40
    created = [r for r in backend.hit("/tasks") if r["method"] == "POST"][-1]["body"]
    assert created["requester_id"] is None
    assert created["status"] == "new"
    assert created["requester_email"] == "lan@example.com"
    # Only the hash is stored; the token itself never reaches the database.
    assert created["guest_token_hash"] == token_hash(token) and token not in str(backend.requests)
    assert not backend.hit("/auth/v1/user")  # no sign-in involved


def test_guest_submission_ignores_injected_fields(client, backend):
    status, _ = post(client, "public/tasks", {**GOOD, "status": "delivered", "requester_id": TASK_ID, "guest_token_hash": "x"})
    assert status == 201
    created = [r for r in backend.hit("/tasks") if r["method"] == "POST"][-1]["body"]
    assert created["status"] == "new" and created["requester_id"] is None and created["guest_token_hash"] != "x"


@pytest.mark.parametrize("bad", [{"name": ""}, {"email": "not-an-email"}, {"title": ""}, {"requested_deadline": "bad"},
                                 {"attachment_url": "javascript:alert(1)"}, {"website": "http://spam"}])
def test_guest_submission_validation_and_honeypot(client, backend, bad):
    assert post(client, "public/tasks", {**GOOD, **bad})[0] == 400


def test_guest_daily_limit(client, backend):
    backend.guest_quota_ok = False
    assert post(client, "public/tasks", GOOD)[0] == 429


def test_cross_origin_guest_post_blocked(client, backend):
    assert post(client, "public/tasks", GOOD, origin="https://evil.example")[0] == 403


def test_tracking_requires_valid_token(client, backend):
    backend.guest_hash = token_hash("A" * 43)
    assert post(client, "public/track", {})[0] == 404
    assert post(client, "public/track", {"token": "short"})[0] == 404
    assert post(client, "public/track", {"token": "B" * 43})[0] == 404
    status, data = post(client, "public/track", {"token": "A" * 43})
    assert status == 200
    assert data["task"]["title"] == "Guest task"
    assert "guest_token_hash" not in data["task"] and "requester_email" not in data["task"]


def test_guest_comment_and_accept(client, backend):
    token = "C" * 43
    backend.guest_hash = token_hash(token)
    assert post(client, "public/comment", {"token": token, "body": "Thêm thông tin"})[0] == 200
    assert backend.hit("/events")[-1]["body"]["actor_id"] is None
    backend.task_status = "accepted"
    assert post(client, "public/accept", {"token": token})[0] == 403
    backend.task_status = "review"
    assert post(client, "public/accept", {"token": token})[0] == 200


def test_guest_ai_is_rate_limited_and_needs_key(client, backend):
    status, data = post(client, "public/ai", {"message": "Làm poster"})
    assert status == 503 and "OPENAI_API_KEY" in data["error"]
    backend.guest_quota_ok = False
    assert post(client, "public/ai", {"message": "x"})[0] == 429


def test_managing_still_requires_sign_in(client, backend):
    for route in ("data", f"tasks/{TASK_ID}/events"):
        assert client.get("/api/index?route=" + route).status_code == 401
    for route in (f"tasks/{TASK_ID}/plan", f"tasks/{TASK_ID}/timer", f"tasks/{TASK_ID}/status", "settings"):
        assert post(client, route, {})[0] == 401


def test_secret_hash_never_returned_to_signed_in_users(call):
    status, data = call("data", mode="manager")
    assert status == 200
    assert all("guest_token_hash" not in t for t in data["tasks"])


def test_unknown_public_route(client, backend):
    assert post(client, "public/delete", {})[0] == 404
