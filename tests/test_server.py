"""HTTP smoke tests (ported from tests/server.test.mjs): static app loads, production
operations fail closed without services, secrets are not served."""

import pytest

from conftest import ENV_KEYS


@pytest.fixture
def unconfigured(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("path,mime", [("/", "text/html"), ("/app.js", "text/javascript"),
                                       ("/planner.mjs", "text/javascript"), ("/demo.mjs", "text/javascript"),
                                       ("/guest.mjs", "text/javascript"), ("/requests.mjs", "text/javascript"),
                                       ("/style.css", "text/css"), ("/guide.html", "text/html"),
                                       ("/guide.css", "text/css")])
def test_static_files_load_with_correct_types(client, unconfigured, path, mime):
    r = client.get(path)
    assert r.status_code == 200
    assert r.mimetype == mime
    assert len(r.data) > 100
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_public_guide_links_both_roles_and_download(client, unconfigured):
    home = client.get("/").get_data(as_text=True)
    guide = client.get("/guide.html").get_data(as_text=True)
    assert '/guide.html#requester' in home
    assert '/guide.html#manager' in home
    assert 'id="requester"' in guide and 'id="manager"' in guide
    assert 'flowtime-user-guide.pdf' in guide


def test_public_guide_pdf_download(client, unconfigured):
    pdf = client.get("/flowtime-user-guide.pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF-")
    assert len(pdf.data) > 10_000


def test_unconfigured_server_fails_closed(client, unconfigured):
    assert client.get("/api/index?route=config").get_json()["configured"] is False
    r = client.post("/api/index?route=tasks", json={})
    assert r.status_code == 503
    assert client.get("/api/cron").status_code == 401


@pytest.mark.parametrize("path", ["/.env", "/../.env", "/app.py", "/flowtime/db.py", "/%2e%2e/app.py"])
def test_secrets_and_source_are_not_served(client, unconfigured, path):
    assert client.get(path).status_code == 404
