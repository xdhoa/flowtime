import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402
from flowtime import http  # noqa: E402

MANAGER = "11111111-1111-4111-8111-111111111111"
REQUESTER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
TASK_ID = "44444444-4444-4444-8444-444444444444"

ENV_KEYS = (
    "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "FLOWTIME_MANAGER_ID", "APP_URL",
    "OPENAI_API_KEY", "RESEND_API_KEY", "EMAIL_FROM", "MANAGER_EMAIL", "CRON_SECRET",
)


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


class FakeBackend:
    """Stands in for Supabase Auth/REST, OpenAI and Resend."""

    def __init__(self):
        self.mode = "requester"
        self.requests = []
        self.task_status = "new"
        self.guest_hash = None  # hash of the tracking token that "exists" in the fake DB
        self.guest_quota_ok = True

    def __call__(self, method, url, headers=None, data=None, timeout=None, **_):
        u = urlsplit(url)
        body = json.loads(data) if data else None
        self.requests.append({"method": method, "path": u.path, "query": parse_qs(u.query), "body": body, "headers": headers or {}})
        if u.path == "/auth/v1/user" and method == "GET":
            uid = MANAGER if self.mode == "manager" else REQUESTER
            # Metadata tries to claim manager/admin; the server must ignore it.
            return FakeResponse({"id": uid, "email": "person@example.com", "email_confirmed_at": "2026-01-01",
                                 "user_metadata": {"name": "Test", "manager": True, "role": "admin"}})
        if u.path.endswith("/rpc/consume_quota"):
            return FakeResponse(True)
        if u.path.endswith("/rpc/consume_guest_quota"):
            return FakeResponse(self.guest_quota_ok)
        if u.path.endswith("/tasks"):
            if method == "POST":
                return FakeResponse([{**body, "id": TASK_ID}], 201)
            if method == "PATCH":
                return FakeResponse([])
            query = parse_qs(u.query)
            if "guest_token_hash" in query:
                if self.guest_hash and query["guest_token_hash"] == ["eq." + self.guest_hash]:
                    return FakeResponse([{"id": TASK_ID, "requester_id": None, "requester_name": "Guest", "requester_email": "g@example.com",
                                          "status": self.task_status, "title": "Guest task", "requested_deadline": "2026-11-05T10:00Z",
                                          "guest_token_hash": self.guest_hash, "result": "Done"}])
                return FakeResponse([])
            return FakeResponse([{"id": TASK_ID, "requester_id": OTHER if self.mode == "other-task" else REQUESTER,
                                  "guest_token_hash": "should-never-leave-the-server",
                                  "requester_email": "person@example.com", "status": self.task_status, "title": "Proposal",
                                  "requested_deadline": "2026-11-05T10:00Z", "updated_at": "2026-11-01T00:00Z"}])
        if u.path.endswith("/plans"):
            return FakeResponse([{"task_id": TASK_ID, "estimate_minutes": 90, "priority": 2, "private_notes": "PRIVATE"}])
        return FakeResponse([])

    def hit(self, suffix):
        return [r for r in self.requests if r["path"].endswith(suffix)]


@pytest.fixture
def backend(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-test-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-test-key")
    monkeypatch.setenv("FLOWTIME_MANAGER_ID", MANAGER)
    monkeypatch.setenv("APP_URL", "https://flowtime.example")
    fake = FakeBackend()
    monkeypatch.setattr(http, "send", fake)
    return fake


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture
def call(client, backend):
    def _call(route, method="GET", body=None, origin=None, mode="requester", raw=None):
        backend.mode = mode
        headers = {"Authorization": "Bearer test-token", "Host": "flowtime.example", "X-Forwarded-Proto": "https"}
        if origin:
            headers["Origin"] = origin
        kwargs = {"headers": headers}
        if raw is not None:
            kwargs["data"], kwargs["content_type"] = raw, "application/json"
        elif body is not None:
            kwargs["json"] = body
        r = client.open("/api/index?route=" + route, method=method, **kwargs)
        return r.status_code, r.get_json()

    return _call
