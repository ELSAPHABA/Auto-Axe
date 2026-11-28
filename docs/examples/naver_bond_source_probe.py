#!/usr/bin/env python3
import datetime as dt
import sys

PAGE = "https://m.stock.naver.com/marketindex/bond/US2YT=RR"
DATA = "https://m.stock.naver.com/front-api/marketIndex/bondList"

def extract(payload):
    if payload.get("isSuccess") is not True:
        raise ValueError("Unexpected or unsuccessful Naver response")
    matches = [r for r in payload.get("result", [])
               if r.get("reutersCode") == "US2YT=RR"]
    if len(matches) != 1:
        raise ValueError("US2YT=RR is missing or duplicated")
    row = matches[0]
    source_time = dt.datetime.fromisoformat(row["localTradedAt"])
    if source_time.tzinfo is None:
        raise ValueError("Missing source timestamp timezone")
    return {
        "series": "UST_2Y",
        "value": float(row["closePrice"].replace(",", "")),
        "unit": "percent",
        "reuters_code": row["reutersCode"],
        "source_event_at": source_time.isoformat(),
        "provider_declared_delay_minutes": row.get("delayTime"),
        "provider_data_type": row.get("priceDataType"),
        "source_market_status": row.get("marketStatus"),
        "source_url": PAGE,
        "scrape_permission_verified_by_operator": True,
        "received_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

def main():
    sys.exit("Naver 2Y retired; use the approved Toss worker or Treasury daily fallback")


if __name__ == "__main__":
    main()
