from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from hashtag_bot.fwp_source import SourceAccessDeniedError, SourceError, fetch_text, make_session


def run_server(statuses):
    calls = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls["count"] += 1
            status = statuses[min(calls["count"] - 1, len(statuses) - 1)]
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, calls


def test_http_403_raises_access_denied_without_retry():
    server, calls = run_server([403])
    try:
        with pytest.raises(SourceAccessDeniedError):
            fetch_text(make_session(), f"http://127.0.0.1:{server.server_port}/fixtures")
        assert calls["count"] == 1
    finally:
        server.shutdown()


def test_http_500_is_retried_then_succeeds():
    server, calls = run_server([500, 500, 200])
    try:
        assert fetch_text(make_session(), f"http://127.0.0.1:{server.server_port}/fixtures") == "ok"
        assert calls["count"] == 3
    finally:
        server.shutdown()


def test_source_errors_do_not_contain_discord_secret():
    secret = "SECRETtoken"
    server, _calls = run_server([403])
    try:
        with pytest.raises(SourceError) as exc_info:
            fetch_text(make_session(), f"http://127.0.0.1:{server.server_port}/fixtures")
        assert secret not in str(exc_info.value)
    finally:
        server.shutdown()
