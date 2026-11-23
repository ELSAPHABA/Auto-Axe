# 미국 주식·ETF 누적 거래량 1초 주기 스냅샷 — yfinance WebSocket

> Auto-Axe 지표 소스 명세 · 2026-11-23 · **문서 등록 완료 / 실제 NVDA·QLD WS 수신 빈도·데이터 지연 미검증 / 운영 수집기 미구현**

## 1. 목표와 정확한 보장 범위

**대상:** 미국 상장 개별 주식(예: NVIDIA `NVDA`)과 ETF(예: ProShares Ultra QQQ `QLD`)의 **당일 누적 거래량을 매초 한 번씩 최신 상태로 출력·기록**한다.

**핵심 방식:** `yfinance.AsyncWebSocket`에 `NVDA`, `QLD`를 구독하고, 수신 콜백이 보관한 마지막 `day_volume`을 **별도 로컬 1Hz 샘플러**가 1초 간격으로 읽는다. **Yahoo가 1초마다 새로운 거래량 메시지를 보내 준다는 의미가 아니다.** 새 메시지가 없으면 직전 누적 거래량을 **같은 원본 시각 및 `stale/no_update` 플래그를 유지한 채** 재표시한다. 직전 값이 0일 때 데이터 없는 구간에 가짜 0주를 채우지 않는다.

| 구분 | 데이터 소스 | 제공/처리 범위 |
|---|---|---|
| 원본 업데이트 | Yahoo Finance 스트림 → yfinance `AsyncWebSocket` | **이벤트 기반**, 실제 빈도는 종목·시간·계정·지역에 따라 다를 수 있으며 **1초 보장 없음** |
| 원본 거래량 | `day_volume` | Yahoo가 제공한 **당일 누적 거래량**; 개별 체결 수량/매초 거래량이 아님 |
| 1초 샘플링 | Auto-Axe 로컬 1Hz scheduler | **1초마다 가장 최근 수신한 누적값** 또는 `no_data/stale` 상태 출력 |
| 샘플 간 차이 | 이전 유효 누적값과 현재 누적값의 차분 | **마지막 새로운 관측 사이**의 증가량만 의미. 새 틱이 없다면 '그 1초에 거래가 없었다'고 추정하지 않음 |
| 실제 통합시장 1초 체결량 | 거래소/SIP 체결원장 필요 | Yahoo WS로 무지연·누락 없는 통합체결/원시 초봉을 보장하지 않음 |

## 2. 공식 API 및 필드 근거

- [yfinance 공식 WebSocket](https://ranaroussi.github.io/yfinance/reference/yfinance.websocket.html): `WebSocket`, `AsyncWebSocket`, `subscribe(symbols)`, `listen(message_handler)`.
- [공식 PricingData Protocol Buffers 스키마](https://github.com/ranaroussi/yfinance/blob/main/yfinance/pricing.proto): `id`(종목), `time`(원본 갱신 시각), `price`, `day_volume`(sint64), `market_hours`, `last_size`. 이 필드들이 **스키마에 존재함**과 **매 메시지에 채워져 도착함**은 다른 문제다.
- [yfinance WS 구현](https://github.com/ranaroussi/yfinance/blob/main/yfinance/live.py): Base64 포장된 Protobuf 메시지를 `MessageToDict(..., preserving_proto_field_name=True)`로 콜백에 전달. `sint64` 값은 JSON 변환 시 **숫자가 아닌 문자열일 수 있으므로** `int()` 정규화가 필요하며 빈 필드는 누락될 수 있다.
- [법적 안내](https://ranaroussi.github.io/yfinance/): 이 라이브러리는 Yahoo의 공식 제휴 SDK가 아니며 연구·교육 및 개인용 사용을 위한 라이브러리. **자동 저장·장기 DB 축적·재배포 및 상업/자동매매 사용권은 Yahoo/원천 제공자의 약관을 별도로 확인**. 무료 접속과 수집 권한은 동의어가 아니다.

## 3. Auto-Axe 정규화 필드

| 필드 | 권장 값/뜻 |
|---|---|
| `series_id` | `US_STOCK_DAILY_CUM_VOLUME_1S` — 모든 미국 주식/ETF 공통 지표 타입 |
| `symbol` | `NVDA`, `QLD` 및 구독 목록. 다중 티커 시 `(symbol, sampled_at_utc)` 복합 키 |
| `provider` | `yfinance_yahoo_stream` |
| `exchange/asset_type` | Yahoo `exchange`/ETF·주식 구분. 코드에서 추측해 주입하지 않음 |
| `day_volume` | 정수 주 단위 당일 누적 거래량. 원본 필드가 없으면 **null** |
| `source_event_at` | `time` 정규화. Epoch 밀리초·초 여부는 실측값으로 검증, UTC 저장 |
| `last_received_at_utc` | 그 종목의 최신 유효 콜백 수신 UTC |
| `sampled_at_utc` | 1초 스케줄러가 스냅샷을 저장한 UTC |
| `source_age_sec` | `sampled_at - source_event_at`; 원천 지연·클라이언트 시계 차이 가능성 포함 |
| `receive_age_sec` | `sampled_at - last_received_at` |
| `updated_since_previous_sample` | 마지막 1초 샘플 후 **새 유효 메시지**가 있었는지 |
| `data_status` | `fresh` / `no_update` / `stale` / `no_data` / `disconnected` / `session_reset` |
| `market_hours` | 공급자가 실어 보낸 원문; 정규장/프리·애프터마켓/휴장 처리에 활용 |
| `delta_since_last_new_observation` | **새 유효 메시지** 사이의 변화량만. 매초 체결량이 아니다 |

**세션 처리:** 장 시작·거래일 변경(미국 동부시간, DST)·Yahoo 원본 누적량 감소·소급 수정 때는 `session_reset`으로 처리하고, 전날 또는 다른 세션의 누적값에서 빼지 않는다. `day_volume`의 실제 세션 범위(정규장만/시간외 포함)는 NVDA/QLD 실데이터로 확인해야 한다.

## 4. 구현 예시 — WebSocket 이벤트 수신 + 로컬 1초 스냅샷

> **참고용 구현 설계 예시**. 2026-11-23 현재 이 예시의 NVDA/QLD 실제 종목 WS 메시지 빈도는 검증하지 않았다. `AsyncWebSocket.listen`은 이벤트가 올 때 콜백을 호출하며, 별도의 `sample_once_per_second`는 `time.monotonic()` 기준 1Hz를 유지한다. 예시 출력의 `fresh`는 **방금 로컬에 새 메시지가 들어온 경우**를 뜻하며 거래소 무지연 시세 보증이 아니다.

```python
import asyncio
import json
import time
from datetime import datetime, timezone

import yfinance as yf

SYMBOLS = {"NVDA", "QLD"}
latest = {}
sampled_sequence = {}
STALE_AFTER_SEC = 5.0  # Auto-Axe 내부 표시 기준. 공급자의 공식 지연기준 아님.


def utc_iso(unix_seconds):
    return datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat()


def on_quote(msg):
    symbol = msg.get("id")
    if symbol not in SYMBOLS or "day_volume" not in msg:
        return
    try:
        volume = int(msg["day_volume"])  # Protobuf int64 may be a JSON string
        raw_time = int(msg["time"])
        event_seconds = raw_time / 1000 if raw_time >= 100_000_000_000 else raw_time
    except (KeyError, TypeError, ValueError):
        return
    if volume < 0:
        return

    prev = latest.get(symbol)
    reset = prev is not None and volume < prev["volume"]
    if prev and event_seconds < prev["event_seconds"]:
        return  # Out-of-order message

    latest[symbol] = {
        "volume": volume,
        "event_seconds": event_seconds,
        "received_seconds": time.time(),
        "market_hours": msg.get("market_hours"),
        "sequence": (prev["sequence"] + 1) if prev else 1,
        "reset": reset,
    }


async def sample_once_per_second():
    next_tick = time.monotonic()
    while True:
        next_tick += 1.0
        await asyncio.sleep(max(0, next_tick - time.monotonic()))
        now = time.time()
        for symbol in sorted(SYMBOLS):
            record = latest.get(symbol)
            if record is None:
                out = {"symbol": symbol, "sampled_at_utc": utc_iso(now),
                       "day_volume": None, "data_status": "no_data"}
            else:
                changed = record["sequence"] != sampled_sequence.get(symbol)
                age = now - record["received_seconds"]
                status = ("stale" if age > STALE_AFTER_SEC else
                          "session_reset" if changed and record["reset"] else
                          "fresh" if changed else "no_update")
                out = {
                    "symbol": symbol,
                    "sampled_at_utc": utc_iso(now),
                    "source_event_at": utc_iso(record["event_seconds"]),
                    "last_received_at_utc": utc_iso(record["received_seconds"]),
                    "day_volume": record["volume"],
                    "updated_since_previous_sample": changed,
                    "receive_age_sec": round(age, 3),
                    "source_age_sec": round(now - record["event_seconds"], 3),
                    "market_hours": record["market_hours"],
                    "data_status": status,
                }
                sampled_sequence[symbol] = record["sequence"]
            print(json.dumps(out), flush=True)


async def main():
    async with yf.AsyncWebSocket(verbose=False) as ws:
        await ws.subscribe(sorted(SYMBOLS))
        await asyncio.gather(
            ws.listen(on_quote),
            sample_once_per_second(),
        )


if __name__ == "__main__":
    asyncio.run(main())
```

설치: `python -m pip install -U yfinance`

이 예시에서 **`day_volume`은 주어진 1초 시점에 알려진 최신 누적값**이며, `data_status=no_update`인 행은 새 거래량 측정이 아니다. 위 예시는 세션 날짜·네트워크 재연결·영구 중복제거 등을 완성한 운영 코드가 아니므로, 실제 배포 전 추가 검증이 필요하다.

## 5. 실측 검증 및 운영 체크리스트

1. **미국 정규장** NVDA와 QLD를 각각 구독하여 `id`, `day_volume`, `time`, `market_hours`의 실제 포함 여부, 단위 및 수신 빈도를 30분 이상 계측.
2. 1Hz 로컬 샘플 출력은 정상 동작하더라도 **실제 Yahoo 메시지 초당 건수**, 1/5/15초 무업데이트 비율 및 `source_age_sec`를 별도 계산.
3. 누적 거래량이 감소하거나 장중 기준이 리셋될 때 `session_reset`으로 표기. 프리/애프터/정규장 혼용 여부 검사.
4. 재연결 후 오래된 마지막 값 유지 금지. WS 연결이 끊기면 최신값에 `disconnected` 표시하고 원본 복귀 전 `fresh` 표시하지 않기.
5. `Ticker.history(interval='1m')`의 `Volume`은 **분봉 거래량**이므로 WS `day_volume`과 별도 저장. 1분봉을 매초 HTTP 요청하는 방식을 **대체 설계로 사용하지 않음**.
6. 특정 거래소·사이트의 표시상 '실시간'과 무지연/시장전체 SIP 거래량을 혼동하지 않음. 수집량·재배포권·자동매매 사용권 최종 검토.

## 6. 현재 작업 범위

- **문서 등록**: 완료
- **NVDA·QLD WebSocket 구독의 장중 메시지/초당 갱신 실측**: 미검증
- **Auto-Axe 운영 수집기 `docs/examples/realtime_collector.py`에 별도 1Hz 명령 구현**: 미구현 (사용자가 이번 턴에서 문서 기록만 요청)
- **API 사용권/수집 데이터 저장 및 자동매매 활용 승인**: 별도 확인 필요

관련 문서: [지표별 데이터 출처](./Indicator_Data_Sources.md) · [실시간 데이터](./Real_Time_Data_Sources.md) · [수집기 설계](./Collector_Design.md) · [yfinance 기존 검증](./YFinance_Data_Validation.md).
