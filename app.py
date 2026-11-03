"""Flowtime — Flask application entry point.

Local (Windows):   python app.py            -> http://localhost:3000
Production (WSGI): gunicorn app:app         (Render/Linux)  or Vercel zero-config Flask (detects `app`)
"""

import logging
import mimetypes
import os
from pathlib import Path

from flask import Flask, abort, send_from_directory

from flowtime.api import bp as api_blueprint

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"


def load_dotenv(path=ROOT / ".env"):
    """Minimal .env loader for local development. Real environment variables always win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_dotenv()

# Windows registries sometimes map .js to text/plain, which breaks <script type="module">.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# static_folder=None: Flask's static handler is not used. On Vercel the CDN serves public/;
# locally and on other hosts the explicit routes below serve the same files.
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
app.register_blueprint(api_blueprint)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
}


@app.after_request
def security_headers(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


@app.errorhandler(413)
def too_large(_error):
    return {"error": "Yêu cầu quá lớn."}, 413


@app.get("/")
def index():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/<path:filename>")
def public_file(filename):
    # send_from_directory rejects path traversal; only files inside public/ are reachable.
    if filename.startswith("api/"):
        abort(404)
    return send_from_directory(PUBLIC, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    print(f"Flowtime: http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
