"""Scrapling Selector-based *offline* fixture parsing. Live DOM remains unverified."""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from scrapling import Selector

from autoaxe_scraper.policy import fixed_target

DRAM_ITEMS = {
    "DDR5 UDIMM 16GB 4800/5600": "DRAM_DDR5_UDIMM_AUTO",
    "DDR5 RDIMM 32GB 4800/5600": "DRAM_DDR5_RDIMM_AUTO",
}


class SchemaChanged(ValueError):
    pass


def text(node: Any) -> str:
    return " ".join(" ".join(node.css("::text").getall()).split())


def decimal(raw: str, *, nonnegative: bool = False) -> str:
    try:
        if not re.fullmatch(r"-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", raw):
            raise ValueError("invalid source numeric grammar")
        value = Decimal(raw.replace(",", ""))
        if not value.is_finite() or (nonnegative and value < 0):
            raise ValueError("invalid source number")
    except (InvalidOperation, ValueError) as exc:
        raise SchemaChanged("invalid/missing numeric value") from exc
    return str(value)


def parse_dram(html: str) -> list[dict[str, Any]]:
    page = Selector(html)
    sections = [
        section
        for section in page.css("section")
        if any(text(title) == "Module Spot Price" for title in section.css("h2,h3"))
    ]
    if len(sections) != 1:
        raise SchemaChanged("unique Module Spot Price section absent")
    section = sections[0]
    stamps = section.css("[data-last-update]")
    tables = section.css("table")
    if len(stamps) != 1 or len(tables) != 1:
        raise SchemaChanged("section clock/table ambiguous")
    try:
        source_at = (
            datetime.strptime(stamps[0].attrib.get("data-last-update", ""), "%Y-%m-%d %H:%M")
            .replace(tzinfo=ZoneInfo("Asia/Taipei"))
            .astimezone(UTC)
            .isoformat()
        )
    except ValueError as exc:
        raise SchemaChanged("missing GMT+8 provider update time") from exc
    rows = tables[0].css("tr")
    if not rows:
        raise SchemaChanged("empty module table")
    columns = [text(item) for item in rows[0].css("th")]
    if columns.count("Item") != 1 or columns.count("Session Average") != 1:
        raise SchemaChanged("missing/duplicate exact table header")
    item_idx, value_idx = columns.index("Item"), columns.index("Session Average")
    result: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        cells = row.css("td")
        if len(cells) != len(columns):
            raise SchemaChanged("unverified row/colspan schema")
        item = text(cells[item_idx])
        if item not in DRAM_ITEMS:
            continue
        sid = DRAM_ITEMS[item]
        if sid in result:
            raise SchemaChanged("duplicate target module")
        value = decimal(text(cells[value_idx]), nonnegative=True)
        if Decimal(value) <= 0:
            raise SchemaChanged("nonpositive module price")
        result[sid] = {
            "series_id": sid,
            "item": item,
            "value": value,
            "source_event_at": source_at,
            "unit": None,
            "unit_verified": False,
            "source_id": "dramexchange",
            "quality": "manual_review_required",
        }
    if set(result) != set(DRAM_ITEMS.values()):
        raise SchemaChanged("missing module target row")
    return [result[sid] for sid in sorted(result)]


def parse_cnn(html: str) -> dict[str, Any]:
    blocks = Selector(html).css('[data-source="cnn-fear-greed"]')
    if len(blocks) != 1:
        raise SchemaChanged("CNN widget not verified")
    score = decimal(blocks[0].attrib.get("data-score", ""))
    if not 0 <= Decimal(score) <= 100:
        raise SchemaChanged("CNN score out of bounds")
    category = blocks[0].attrib.get("data-category")
    if category not in ("Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"):
        raise SchemaChanged("CNN category mismatch")
    return {
        "series_id": "CNN_FEAR_GREED_CNN",
        "value": score,
        "category": category,
        "source_event_at": None,
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
    }


def parse_naver(html: str) -> dict[str, Any]:
    blocks = Selector(html).css('[data-symbol="US2YT=RR"]')
    if len(blocks) != 1:
        raise SchemaChanged("Naver 2Y widget not verified")
    item = blocks[0]
    value = decimal(item.attrib.get("data-yield", ""))
    try:
        stamp = datetime.fromisoformat(item.attrib["data-time"])
        if stamp.tzinfo is None or stamp > datetime.now(UTC):
            raise ValueError("naive or future timestamp")
    except (KeyError, ValueError) as exc:
        raise SchemaChanged("missing Naver source timestamp") from exc
    return {
        "series_id": "UST_2Y_NAVER",
        "value": value,
        "source_event_at": stamp.astimezone(UTC).isoformat(),
        "quality": "manual_review_required",
    }


def parse_seibro(html: str, *, country: str, period: str, basis: str) -> list[dict[str, Any]]:
    if country not in ("US", "ALL", "HK", "CN", "JP", "VN"):
        raise ValueError("invalid SEIBro country")
    if period not in ("1", "2", "3", "4", "5") or basis not in ("1", "2", "3", "4"):
        raise ValueError("invalid SEIBro period/basis")
    tables = Selector(html).css('[data-source="seibro-top50"]')
    if len(tables) != 1:
        raise SchemaChanged("SEIBro result table not verified")
    rows: list[dict[str, Any]] = []
    for node in tables[0].css("tbody tr"):
        cells = node.css("td")
        if len(cells) != 8:
            raise SchemaChanged("unknown SEIBro column mapping")
        fields = [text(item) for item in cells]
        try:
            rank = int(fields[0])
        except ValueError as exc:
            raise SchemaChanged("invalid SEIBro rank") from exc
        if not 1 <= rank <= 50 or not re.fullmatch(r"[A-Z0-9]{12}", fields[2]):
            raise SchemaChanged("invalid rank/ISIN")
        rows.append(
            {
                "rank": rank,
                "country_name": fields[1],
                "isin": fields[2],
                "security_name": fields[3],
                "buy_settlement_usd": decimal(fields[4], nonnegative=True),
                "sell_settlement_usd": decimal(fields[5], nonnegative=True),
                "gross_settlement_usd": decimal(fields[6], nonnegative=True),
                "net_buy_settlement_usd": decimal(fields[7]),
                "country_code": country,
                "period_code": period,
                "rank_basis": basis,
                "currency": "USD",
                "top50_coverage": True,
                "source_event_at": None,
                "quality": "manual_review_required",
            }
        )
    if not rows or len(rows) > 50 or len({r["rank"] for r in rows}) != len(rows):
        raise SchemaChanged("missing/duplicate TOP50 results")
    return rows


def parse_offline(source: str, html: str, params: dict[str, str] | None = None) -> Any:
    if fixed_target(source).api_only:
        raise SchemaChanged("API-only source has no HTML parser")
    if len(html.encode("utf-8")) > 2_000_000:
        raise ValueError("HTML exceeds source limit")
    if source == "dramexchange":
        return parse_dram(html)
    if source == "cnn":
        return parse_cnn(html)
    if source == "naver":
        return parse_naver(html)
    if source == "seibro":
        args = params or {}
        return parse_seibro(
            html, country=args["country"], period=args["period"], basis=args["basis"]
        )
    raise ValueError("unknown source")
