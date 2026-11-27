"""Explicit reviewed static DOM contract; synthetic selectors are never live defaults."""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from scrapling import Selector

from autoaxe_scraper.parsers import DRAM_ITEMS, SchemaChanged, decimal, text
from autoaxe_scraper.policy import fixed_target

FIELDS = {
    "naver": {"root", "symbol", "yield", "timestamp"},
    "dramexchange": {"root", "title", "table", "timestamp"},
}


@dataclass(frozen=True)
class DOMContract:
    source_id: str
    permission_version: int
    expires_at: datetime
    selectors: dict[str, str]

    def check(self, source: str, version: int | None = None) -> None:
        if (
            source != self.source_id
            or self.expires_at <= datetime.now(UTC)
            or (version is not None and version != self.permission_version)
        ):
            raise SchemaChanged("reviewed DOM contract expired or scope changed")


def load_contract(source: str) -> DOMContract:
    path = os.getenv("AUTOAXE_SCRAPE_DOM_CONTRACT")
    digest = os.getenv("AUTOAXE_SCRAPE_DOM_CONTRACT_SHA256")
    if not path or not digest:
        raise SchemaChanged("reviewed DOM contract required")
    with Path(path).open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384 or hashlib.sha256(raw).hexdigest() != digest:
        raise SchemaChanged("DOM contract hash mismatch")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or set(data)
        != {
            "version",
            "source_id",
            "source_url",
            "permission_version",
            "expires_at",
            "evidence_ref",
            "selectors",
        }
        or type(data["version"]) is not int
        or data["version"] != 1
        or data["source_id"] != source
        or source not in FIELDS
        or data["source_url"] != fixed_target(source).url
        or type(data["permission_version"]) is not int
        or data["permission_version"] < 1
        or not isinstance(data["evidence_ref"], str)
        or not 1 <= len(data["evidence_ref"].strip()) <= 512
        or not isinstance(data["selectors"], dict)
        or set(data["selectors"]) != FIELDS[source]
        or any(
            not isinstance(s, str) or not 1 <= len(s) <= 256 or "::" in s
            for s in data["selectors"].values()
        )
    ):
        raise SchemaChanged("invalid reviewed DOM contract")
    expires = datetime.fromisoformat(data["expires_at"])
    if expires.utcoffset() is None:
        raise SchemaChanged("missing contract timezone")
    contract = DOMContract(source, data["permission_version"], expires, data["selectors"])
    contract.check(source)
    return contract


def one(node: Any, selector: str) -> Any:
    matches = node.css(selector)
    if len(matches) != 1:
        raise SchemaChanged("reviewed DOM selector absent or ambiguous")
    return matches[0]


def stamp(raw: str, *, dram: bool = False) -> str:
    try:
        if dram:
            match = re.fullmatch(
                r"Last Update:\s*([A-Z][a-z]{2})\.\s*([0-9]{1,2}) "
                r"([0-9]{4}) ([0-9]{2}:[0-9]{2}) \(GMT\+8\)",
                raw,
            )
            if not match:
                raise ValueError("unverified update label")
            month, day, year, hm = match.groups()
            months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
            value = datetime.fromisoformat(
                f"{year}-{months.index(month) + 1:02}-{int(day):02}T{hm}"
            )
            value = value.replace(tzinfo=timezone(timedelta(hours=8)))
        else:
            value = datetime.fromisoformat(raw)
        if value.utcoffset() is None or value > datetime.now(UTC):
            raise ValueError("missing timezone or future source time")
        return value.astimezone(UTC).isoformat()
    except ValueError as exc:
        raise SchemaChanged("invalid displayed source timestamp") from exc


def parse_reviewed(contract: DOMContract, html: str) -> Any:
    contract.check(contract.source_id)
    if len(html.encode("utf-8")) > 1_000_000:
        raise SchemaChanged("HTML exceeds limit")
    selectors = contract.selectors
    root = one(Selector(html), selectors["root"])

    def get(key: str) -> str:
        return text(one(root, selectors[key]))

    if contract.source_id == "naver":
        if get("symbol") != "US2YT=RR":
            raise SchemaChanged("Naver symbol mismatch")
        return {
            "series_id": "UST_2Y_NAVER",
            "value": decimal(get("yield")),
            "source_event_at": stamp(get("timestamp")),
            "quality": "manual_review_required",
        }
    if contract.source_id != "dramexchange" or get("title") != "Module Spot Price":
        raise SchemaChanged("wrong price section")
    source_at = stamp(get("timestamp"), dram=True)
    rows = one(root, selectors["table"]).css("tr")
    if not rows:
        raise SchemaChanged("missing module rows")
    columns = [text(cell) for cell in rows[0].css("th")]
    if columns.count("Item") != 1 or columns.count("Session Average") != 1:
        raise SchemaChanged("module header mismatch")
    result = {}
    for row in rows[1:]:
        cells = row.css("td")
        if len(cells) != len(columns):
            raise SchemaChanged("module row shape mismatch")
        item = text(cells[columns.index("Item")])
        if item not in DRAM_ITEMS:
            continue
        sid = DRAM_ITEMS[item]
        value = decimal(text(cells[columns.index("Session Average")]))
        if sid in result or Decimal(value) <= 0:
            raise SchemaChanged("duplicate or invalid module price")
        result[sid] = {
            "series_id": sid,
            "value": value,
            "item": item,
            "source_event_at": source_at,
            "unit": None,
            "unit_verified": False,
            "source_id": "dramexchange",
            "quality": "manual_review_required",
        }
    if set(result) != set(DRAM_ITEMS.values()):
        raise SchemaChanged("missing required module")
    return [result[sid] for sid in sorted(result)]
