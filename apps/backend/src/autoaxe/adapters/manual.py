"""Read the existing PoC CSV format without fetching user-supplied URLs."""

import csv
from datetime import datetime
from io import StringIO
from urllib.parse import urlsplit

from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.catalog import MANUAL
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_datetime

HEADERS = [
    "series_id",
    "instrument_type",
    "source_url",
    "as_of_utc",
    "collected_at_utc",
    "frequency",
    "value",
    "unit",
    "category",
    "quote_currency",
    "exchange",
    "contract",
    "source_delay_minutes",
    "operator",
    "note",
    "verification_status",
]


def manual_candidates(csv_text: str) -> list[Candidate]:
    if len(csv_text.encode("utf-8")) > 1_000_000:
        raise ValueError("CSV too large")
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    if reader.fieldnames != HEADERS:
        raise ValueError("invalid CSV header")
    result: list[Candidate] = []
    for row in reader:
        if len(result) >= 1000 or None in row or any(v is None for v in row.values()):
            raise ValueError("invalid CSV rows")
        sid = row["series_id"]
        if sid not in MANUAL or row["unit"] != MANUAL[sid] or not row["operator"].strip():
            raise ValueError("unregistered manual definition or unit")
        url = urlsplit(row["source_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("invalid evidence URL")
        if row["verification_status"] != "unverified":
            raise ValueError("import cannot self-approve")
        received = utc_datetime(datetime.fromisoformat(row["collected_at_utc"]))
        stamp = utc_datetime(datetime.fromisoformat(row["as_of_utc"])) if row["as_of_utc"] else None
        meta = {
            k: v
            for k, v in row.items()
            if k not in ("value", "series_id", "as_of_utc", "collected_at_utc")
        }
        if MANUAL[sid] in ("typed", "status"):
            value = None
            meta["reported_value"] = row["value"]
        else:
            value = decimal_string(row["value"])
        result.append(
            Candidate(
                sid,
                canonical_sha256(row),
                value,
                stamp,
                received,
                received,
                Quality.MANUAL_UNVERIFIED,
                meta,
            )
        )
    return result
