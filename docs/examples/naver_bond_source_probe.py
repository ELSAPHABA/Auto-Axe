#!/usr/bin/env python3
import datetime as dt
import json
import os
import sys
import requests

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
    if os.getenv("AUTO_AXE_NAVER_SCRAPE_AUTHORIZED") != "1":
        sys.exit("Naver automated collection disabled; robots.txt Disallow: /. "
                 "Obtain the rights holder's permission first. "
                 "Use Treasury official DGS2 / BC_2YEAR for daily fallback.")
    r = requests.get(DATA, params={"countryCode": "USA"}, timeout=12,
                     headers={"Accept": "application/json",
                              "User-Agent": os.getenv("AUTO_AXE_USER_AGENT","AutoAxeResearch/0.1")})
    r.raise_for_status()
    print(json.dumps(extract(r.json()), ensure_ascii=False))

if __name__ == "__main__":
    main()
