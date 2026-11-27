import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from autoaxe_scraper.parsers import SchemaChanged
from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.reviewed_dom import DOMContract, load_contract, parse_reviewed
from autoaxe_scraper.worker import BrokerError, run_once


def contract(source, selectors):
    return DOMContract(source, 1, datetime.now(UTC) + timedelta(hours=1), selectors)


def test_no_contract_does_not_claim():
    class NoBroker:
        def post(self, *_):
            pytest.fail("broker contacted without reviewed contract")

    with pytest.raises(BrokerError, match="reviewed DOM"):
        run_once(NoBroker(), "naver")


def test_cnn_html_contract_is_retired():
    c = contract("cnn", {"root": "#widget", "score": ".score", "category": ".category"})
    with pytest.raises(BrokerError, match="JSON-only"):
        run_once(None, "cnn", contract=c)


def test_naver_exact_identity_and_explicit_time():
    c = contract("naver", {"root": "#bond", "symbol": ".s", "yield": ".v", "timestamp": "time"})
    html = (
        '<div id="bond"><b class="s">US2YT=RR</b><span class="v">4.25</span>'
        "<time>2026-11-23T16:00:00+09:00</time></div>"
    )
    assert parse_reviewed(c, html)["source_event_at"] == "2026-11-23T07:00:00+00:00"
    with pytest.raises(SchemaChanged):
        parse_reviewed(c, html.replace("US2YT", "US10YT"))
    with pytest.raises(SchemaChanged):
        parse_reviewed(c, html.replace("+09:00", ""))


def test_dram_module_section_visible_timestamp_and_unknown_unit():
    c = contract(
        "dramexchange", {"root": "#module", "title": "h2", "table": "table", "timestamp": "p"}
    )
    html = (
        '<div id="module"><h2>Module Spot Price</h2><p>Last Update:Aug.3 2026 14:40 (GMT+8)</p>'
        "<table><tr><th>Item</th><th>Weekly High</th><th>Session Average</th></tr>"
        "<tr><td>DDR5 UDIMM 16GB 4800/5600</td><td>15</td><td>12.5</td></tr>"
        "<tr><td>DDR5 RDIMM 32GB 4800/5600</td><td>30</td><td>22.5</td></tr></table></div>"
    )
    rows = parse_reviewed(c, html)
    assert [r["value"] for r in rows] == ["22.5", "12.5"]
    assert all(
        r["unit"] is None and r["source_event_at"] == "2026-08-03T06:40:00+00:00" for r in rows
    )
    with pytest.raises(SchemaChanged):
        parse_reviewed(c, html.replace("GMT+8", "GMT+9"))


def test_manifest_hash_url_expiry_and_scope(tmp_path, monkeypatch):
    path = tmp_path / "contract.json"
    doc = {
        "version": 1,
        "source_id": "naver",
        "source_url": fixed_target("naver").url,
        "permission_version": 7,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "evidence_ref": "synthetic fixture only",
        "selectors": {"root": "#a", "symbol": ".b", "yield": ".c", "timestamp": "time"},
    }

    def write():
        raw = json.dumps(doc).encode()
        path.write_bytes(raw)
        monkeypatch.setenv("AUTOAXE_SCRAPE_DOM_CONTRACT", str(path))
        monkeypatch.setenv("AUTOAXE_SCRAPE_DOM_CONTRACT_SHA256", hashlib.sha256(raw).hexdigest())

    write()
    assert load_contract("naver").permission_version == 7
    path.write_bytes(b"{}")
    with pytest.raises(SchemaChanged):
        load_contract("naver")
    doc["source_url"] = "https://example.com/"
    write()
    with pytest.raises(SchemaChanged):
        load_contract("naver")
