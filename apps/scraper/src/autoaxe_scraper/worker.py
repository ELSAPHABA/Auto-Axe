"""One-shot, permission-gated scraper worker; no DB or provider credentials.

The generic worker deliberately excludes the dedicated DOUGHCON collector and
browser-only SEIBro. Fixture parsers remain unverified against provider DOM.
"""

import argparse
import http.client
import json
import multiprocessing
import os
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from autoaxe_scraper.parsers import SchemaChanged, parse_offline
from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.transport import ProviderHTTPError, SourceBlocked, fetch_exact_html

HTTP_SOURCES = frozenset({"cnn", "dramexchange", "naver"})
BROKER_PATH = "/internal/v1/scrape/jobs"
MAX_BROKER_BYTES = 262_144
JOB_BUDGET_SECONDS = 25


class BrokerError(RuntimeError):
    pass


class Broker(Protocol):
    def post(self, path: str, data: dict[str, Any]) -> Any: ...


class TLSBroker:
    def __init__(self, host: str, port: int, ca: str, cert: str, key: str) -> None:
        if not host or any(c in host for c in "/@?#\\") or not 1 <= port <= 65535:
            raise ValueError("invalid broker address")
        self.host = host
        self.port = port
        self.context = ssl.create_default_context(cafile=ca)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(certfile=cert, keyfile=key)

    def post(self, path: str, data: dict[str, Any]) -> Any:
        payload = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > MAX_BROKER_BYTES:
            raise BrokerError("broker request too large")
        conn = http.client.HTTPSConnection(
            self.host, port=self.port, context=self.context, timeout=4
        )
        try:
            conn.request(
                "POST",
                path,
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = conn.getresponse()
            if response.status != 200:
                raise BrokerError(f"broker rejected request ({response.status})")
            media = response.getheader("content-type", "").split(";", 1)[0].lower()
            if (
                media != "application/json"
                or response.getheader("content-encoding", "identity") != "identity"
            ):
                raise BrokerError("unexpected broker response encoding")
            raw = response.read(MAX_BROKER_BYTES + 1)
            if len(raw) > MAX_BROKER_BYTES:
                raise BrokerError("broker response too large")
            return json.loads(raw)
        finally:
            conn.close()


@dataclass(frozen=True)
class Job:
    job_id: str
    source_id: str
    job_nonce: str
    lease_token: str
    deadline_at: datetime
    lease_expires_at: datetime

    @classmethod
    def parse(cls, data: Any, source: str) -> "Job":
        expected = {
            "job_id",
            "source_id",
            "adapter_version",
            "schema_version",
            "params",
            "job_nonce",
            "lease_token",
            "deadline_at",
            "lease_expires_at",
            "permission_version",
        }
        if (
            not isinstance(data, dict)
            or set(data) != expected
            or source not in HTTP_SOURCES
            or data["source_id"] != source
            or type(data["adapter_version"]) is not int
            or data["adapter_version"] != 1
            or type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["params"] != {}
            or type(data["permission_version"]) is not int
            or data["permission_version"] < 1
        ):
            raise BrokerError("invalid broker job schema")
        try:
            job_id = str(UUID(data["job_id"]))
            deadline = datetime.fromisoformat(data["deadline_at"])
            expiry = datetime.fromisoformat(data["lease_expires_at"])
            if not datetime.now(UTC) < expiry <= deadline:
                raise ValueError("expired lease")
            for name in ("job_nonce", "lease_token"):
                token = data[name]
                if not isinstance(token, str) or not token.isascii() or not 10 <= len(token) <= 256:
                    raise ValueError("invalid lease credential")
        except (TypeError, ValueError, AttributeError) as exc:
            raise BrokerError("invalid job id, time or lease credential") from exc
        return cls(job_id, source, data["job_nonce"], data["lease_token"], deadline, expiry)

    def credentials(self) -> dict[str, str]:
        return {"job_nonce": self.job_nonce, "lease_token": self.lease_token}


def run_once(broker: Broker, source: str) -> str:
    """Claim one exact source; all failures abandon the lease without ingest."""
    if source not in HTTP_SOURCES:
        raise BrokerError("source unavailable to generic HTTP worker")
    data = broker.post(BROKER_PATH + "/claim", {"source_id": source, "lease_seconds": 30})
    if data is None:
        return "idle"
    job = Job.parse(data, source)
    path = f"{BROKER_PATH}/{job.job_id}"

    def permit() -> None:
        if datetime.now(UTC) >= job.deadline_at:
            raise BrokerError("job deadline expired")
        if broker.post(path + "/heartbeat", job.credentials()) != {"status": "leased"}:
            raise BrokerError("lease no longer valid")

    # fetch_exact_html calls permit before and after network I/O. No redirects,
    # browser fallback, arbitrary URL, compression or provider credentials.
    try:
        html = fetch_exact_html(fixed_target(source), permit=permit)
        parsed = parse_offline(source, html)
    except (
        ProviderHTTPError,
        SourceBlocked,
        SchemaChanged,
        OSError,
        http.client.HTTPException,
    ) as exc:
        failure: dict[str, Any] = {**job.credentials(), "source_id": source}
        if isinstance(exc, ProviderHTTPError):
            failure.update(reason="http", http_status=exc.status)
            if exc.retry_header:
                # Oversized or malformed retry instructions fail closed by
                # reporting a schema failure rather than truncating the delay.
                if len(exc.retry_header) > 128 or not exc.retry_header.isascii():
                    failure = {**job.credentials(), "source_id": source, "reason": "schema"}
                else:
                    failure["retry_header"] = exc.retry_header
        else:
            failure["reason"] = (
                "schema" if isinstance(exc, (SourceBlocked, SchemaChanged)) else "transport"
            )
        if broker.post(path + "/failure", failure) != {"status": "failed"}:
            raise BrokerError("failure was not recorded") from exc
        return "failed"
    candidates = parsed if isinstance(parsed, list) else [parsed]
    permit()
    response = broker.post(
        path + "/result",
        {**job.credentials(), "source_id": source, "adapter_version": 1, "candidates": candidates},
    )
    if response not in ({"status": "quarantined"}, {"status": "duplicate"}):
        raise BrokerError("broker did not quarantine candidate")
    return str(response["status"])


def _child(source: str) -> None:
    try:
        broker = TLSBroker(
            os.environ["AUTOAXE_SCRAPE_BROKER_HOST"],
            int(os.environ.get("AUTOAXE_SCRAPE_BROKER_PORT", "8443")),
            os.environ["AUTOAXE_SCRAPE_BROKER_CA"],
            os.environ["AUTOAXE_SCRAPER_CERT"],
            os.environ["AUTOAXE_SCRAPER_KEY"],
        )
        result = run_once(broker, source)
        print(f"scraper: {result}", flush=True)
        if result == "failed":
            raise SystemExit(1)
    except Exception:
        # Provider pages, credentials and arbitrary exception details must not
        # leak into logs. A failed job is fenced by its existing lease expiry.
        print("scraper: collection failed", flush=True)
        raise SystemExit(1) from None


def run_bounded(source: str) -> int:
    # A child process bounds DNS, TLS, slow responses and parser CPU together;
    # socket timeouts alone would not stop a slow-drip response or DNS stall.
    child = multiprocessing.get_context("spawn").Process(target=_child, args=(source,))
    child.start()
    child.join(JOB_BUDGET_SECONDS)
    if child.is_alive():
        child.kill()
        child.join()
        print("scraper: job budget exceeded", flush=True)
        return 1
    return child.exitcode or 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated HTTP scrape worker")
    parser.add_argument("source", choices=sorted(HTTP_SOURCES))
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    while True:
        status = run_bounded(args.source)
        if not args.daemon:
            raise SystemExit(status)
        # Poll only the broker, never the provider without a new fenced lease.
        time.sleep(60)


if __name__ == "__main__":
    main()
