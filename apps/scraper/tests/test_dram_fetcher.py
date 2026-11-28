"""DRAM transport tests; never contact the real provider."""

import os
import socket
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import MagicMock

import pytest

from autoaxe_scraper import dram_fetcher as dram
from autoaxe_scraper.transport import ProviderHTTPError, SourceBlocked


def test_fixed_target_and_permission_checks(monkeypatch):
    fetch = MagicMock(return_value="<html>fixture</html>")
    monkeypatch.setattr(dram, "_fetch_pinned_html", fetch)
    permit = MagicMock()
    resolve = MagicMock(return_value=[(socket.AF_INET, 1, 6, "", ("8.8.8.8", 443))])
    assert dram.fetch_dramexchange_html(permit=permit, resolve=resolve) == "<html>fixture</html>"
    fetch.assert_called_once_with("https://www.dramexchange.com/", "8.8.8.8")
    assert permit.call_count == 3
    fetch.reset_mock()
    resolve.return_value += [(socket.AF_INET, 1, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(SourceBlocked):
        dram.fetch_dramexchange_html(permit=permit, resolve=resolve)
    fetch.assert_not_called()


def test_revocation_after_dns_prevents_fetch(monkeypatch):
    fetch = MagicMock()
    monkeypatch.setattr(dram, "_fetch_pinned_html", fetch)
    permit = MagicMock(side_effect=[None, RuntimeError("revoked")])
    with pytest.raises(RuntimeError, match="revoked"):
        dram.fetch_dramexchange_html(
            permit=permit, resolve=lambda *a, **kw: [(socket.AF_INET, 1, 6, "", ("8.8.8.8", 443))]
        )
    fetch.assert_not_called()


def test_missing_private_client_contract_fails_closed(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value._curl_session = None
    monkeypatch.setattr(dram, "FetcherSession", lambda **kw: session)
    with pytest.raises(SourceBlocked, match="contract unavailable"):
        dram._fetch_pinned_html("https://www.dramexchange.com/", "8.8.8.8")
    session.__enter__.return_value.get.assert_not_called()


@pytest.mark.skipif(
    os.getenv("AUTOAXE_TEST_LOOPBACK_HTTP") != "1",
    reason="requires isolated unmodified loopback HTTPS and openssl",
)
def test_actual_scrapling_pinned_tls(tmp_path, monkeypatch):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=dram.fixture.invalid",
            "-addext",
            "subjectAltName=DNS:dram.fixture.invalid",
        ],
        check=True,
        capture_output=True,
    )
    paths = []
    html = b"<html><body>DRAM fixture</body></html>"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append((self.path, self.headers.get("Host")))
            assert self.headers.get("User-Agent") == "Auto-Axe/0.1 permission-gated research parser"
            assert self.headers.get("Accept-Encoding") == "identity"
            assert self.headers.get("Referer") is None
            status = {"/redirect": 302, "/limit": 429}.get(self.path, 200)
            raw = b"" if status != 200 else html
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(raw)))
            if status == 302:
                self.send_header("Location", "/ok")
            if status == 429:
                self.send_header("Retry-After", "900")
            if self.path == "/compressed":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f"https://dram.fixture.invalid:{server.server_port}"
        # A nonexistent DNS hostname and deliberately unusable proxy prove
        # the pinned destination and explicit no-proxy behavior.
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
        monkeypatch.delenv("NO_PROXY", raising=False)
        try:

            def fetch(path):
                return dram._fetch_pinned_html(root + path, "127.0.0.1", verify=str(cert))

            assert fetch("/ok") == html.decode()
            with pytest.raises(ProviderHTTPError) as exc:
                fetch("/redirect")
            assert exc.value.status == 302
            with pytest.raises(ProviderHTTPError) as exc:
                fetch("/limit")
            assert (exc.value.status, exc.value.retry_header) == (429, "900")
            with pytest.raises(SourceBlocked, match="compressed"):
                fetch("/compressed")
            with pytest.raises(OSError):
                dram._fetch_pinned_html(
                    root.replace("dram.fixture", "wrong.fixture") + "/ok",
                    "127.0.0.1",
                    verify=str(cert),
                )
            with pytest.raises(OSError):
                dram._fetch_pinned_html(root + "/ok", "127.0.0.1")
            monkeypatch.setattr(dram, "MAX_HTML_BYTES", 8)
            with pytest.raises(SourceBlocked, match="size limit"):
                fetch("/ok")
            assert [path for path, _ in paths] == [
                "/ok",
                "/redirect",
                "/limit",
                "/compressed",
                "/ok",
            ]
            assert all(host == f"dram.fixture.invalid:{server.server_port}" for _, host in paths)
        finally:
            server.shutdown()
            thread.join()
