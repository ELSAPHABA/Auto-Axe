import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from autoaxe.entrypoints.scrape_broker import validate_candidates


def test_candidate_schema_rejects_unrelated_and_trade_fields(cnn_details):
    stamp = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    candidate = {
        "series_id": "CNN_FEAR_GREED_CNN",
        "value": "12",
        "category": "Fear",
        "source_event_at": stamp,
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
        "details": cnn_details(stamp),
    }
    validate_candidates("cnn", [candidate])
    for bad in (
        candidate | {"raw_html": "untrusted"},
        candidate | {"automated_trading_allowed": True},
        candidate | {"value": "NaN"},
        candidate | {"series_id": "UST_2Y_NAVER"},
    ):
        with pytest.raises(ValueError):
            validate_candidates("cnn", [bad])


def test_actual_mtls_peer_pin_and_body_limit(tmp_path):
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "offline-test-ca")])

    def builder(name, issuer, key):
        return (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=2))
            .not_valid_after(now + timedelta(hours=1))
        )

    ca = (
        builder(ca_name, ca_name, ca_key)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))

    def issue(name, server=False):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        leaf = builder(subject, ca_name, key).add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        if server:
            leaf = leaf.add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
        cert = leaf.sign(ca_key, hashes.SHA256())
        cert_path, key_path = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return (
            cert_path,
            key_path,
            hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(),
        )

    server_cert, server_key, _ = issue("broker", server=True)
    worker_cert, worker_key, pin = issue("worker")
    other_cert, other_key, _ = issue("other")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    env = os.environ.copy()
    env.pop("AUTOAXE_SCRAPE_BROKER_MARKET_DSN", None)
    env.update(
        {
            "AUTOAXE_SCRAPE_BROKER_HOST": "127.0.0.1",
            "AUTOAXE_SCRAPE_BROKER_PORT": str(port),
            "AUTOAXE_SCRAPE_BROKER_CERT": str(server_cert),
            "AUTOAXE_SCRAPE_BROKER_KEY": str(server_key),
            "AUTOAXE_SCRAPE_BROKER_CLIENT_CA": str(ca_path),
            "AUTOAXE_SCRAPER_CERT_SHA256": pin,
        }
    )

    def request(cert=None, key=None, body=None):
        ctx = ssl.create_default_context(cafile=str(ca_path))
        if cert:
            ctx.load_cert_chain(str(cert), str(key))
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=2)
        try:
            conn.request(
                "POST",
                "/internal/v1/scrape/jobs/claim",
                body=body if body is not None else json.dumps({"source_id": "pizzint"}),
                headers={"Content-Type": "application/json", "X-Client-Certificate": pin},
            )
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    proc = subprocess.Popen(
        [sys.executable, "-m", "autoaxe.entrypoints.scrape_broker"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(80):
            if proc.poll() is not None:
                pytest.fail("broker exited during startup")
            try:
                status = request(worker_cert, worker_key)
            except (ConnectionRefusedError, TimeoutError):
                time.sleep(0.1)
                continue
            break
        else:
            pytest.fail("broker did not start")
        # Actual authenticated identity passes to source guard (no DB/provider call).
        assert status == 403
        with pytest.raises((OSError, http.client.HTTPException)):
            request()  # no certificate, forged header cannot establish mTLS
        with pytest.raises((OSError, http.client.HTTPException)):
            request(other_cert, other_key)  # trusted CA, wrong leaf pin
        assert request(worker_cert, worker_key, b"X" * 262_145) == 413
    finally:
        proc.terminate()
        proc.wait(timeout=5)
