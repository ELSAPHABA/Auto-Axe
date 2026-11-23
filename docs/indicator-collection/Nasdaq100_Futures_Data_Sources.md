# 나스닥 100 선물·연동상품 무료 실시간 수집 방안

> 조사 기준: **2026-11-23** · Auto-Axe 데이터 소스 제안서 · **문서화만 완료, 실제 수집기 구현/WS 수신 검증 전** · 유료 서비스는 기본 설계에서 제외

## 목적과 상품 식별

나스닥 100 선물 시장의 움직임을 최대한 빠르게 파악하되 **거래소 상품·기준 지수·호가통화·지연시간을 구분**한다. 원본 **CME E-mini Nasdaq-100 Futures (NQ)** 및 **Micro E-mini Nasdaq-100 Futures (MNQ)**의 체결가격과 MEXC의 **나스닥 100 지수 연동 영구선물**, Binance의 **QQQ ETF 연동 영구선물**은 **서로 다른 계약**이다. 원본 NQ 가격을 무료 무지연으로 받는다고 주장하지 않는다.

## 소스 우선순위

| 우선순위 | 원본/심볼 | 방법 | 얻는 값 | 실시간성·접근 제한 | 권장 내부 시리즈 |
|---|---|---|---|---|---|
| **1 — 무료 저지연 관련 신호** | **MEXC NAS100_USDT** (UI 표기 NAS100USDT) | MEXC Futures 공개 REST / WebSocket | **나스닥 100 지수 연동 USDT 결제 영구선물** 호가·체결 | WS 메시지는 거래 발생·호가 변경 시 전송. 실측 지연/연속 수신·계약 거래시간 **아직 검증하지 않음** | `NASDAQ100_MEXC_PERP_USDT` |
| **2 — 별도 시장 참고** | **Binance QQQUSDT** | Binance USDⓈ-M Futures 공개 REST / WebSocket | **Invesco QQQ ETF 연동 영구선물** 가격 | 실시간 거래소 계약 틱 가능, 실제 QQQ ETF 주가 및 NQ/NDX 지수 수준과 다름 | `NASDAQ100_BINANCE_QQQ_PERP_USDT` |
| **3 — 실제 CME NQ 비교 기준** | **Yahoo Finance `NQ=F`** | `yfinance.Ticker('NQ=F').history(interval='1m')` 폴링 | Yahoo가 제공하는 **CME NQ 선물 근월물/연속 심볼 시세** | Yahoo 페이지 자체에 **`CME - Delayed Quote`** 명시. 1분봉은 1분 **집계 간격**이지 무지연 1분 이내 수신 보장 아님 | `NASDAQ100_CME_NQ_YAHOO_DELAYED` |
| **4 — 실제 CME 무지연 체결** | **CME NQ·MNQ** | 거래소·중개사·정식 데이터 벤더의 라이선스된 실시간 피드 | **CME 실제 계약 실시간 체결** | 정식 시세 수신 권한/계약·비용이 일반적으로 필요하므로 Auto-Axe의 **무료 우선 기본 범위에서 제외** | `NASDAQ100_CME_NQ_LIVE_LICENSED` (미사용) |

**주의:** `QQQUSDT` 값의 스케일은 QQQ ETF 연계이고 `NQ=F`/MEXC NAS100_USDT와 다를 수 있다. MEXC 지수 연동 영구선물도 CME NQ 선물과 결제·펀딩·거래시간·기준가격·유동성이 다르므로, 원본 NQ의 실시간 대체가격 또는 무위험 차익 가격으로 처리하지 않는다.

## MEXC: 무료 저지연 1순위 조사

- **상장 사실:** MEXC 공식 [지수 선물 상장 공지](https://www.mexc.com/announcements/article/mexc-to-launch-stock-index-futures-starting-with-nas100-us30-sp500-usdt-m-pairs-on-jan-29-17827791533334)는 NAS100USDT를 **2026-01-29** 상장한 것으로 안내한다. [상품 페이지](https://www.mexc.com/futures/NAS100_USDT).
- **심볼 표기:** 웹 거래쌍 NAS100USDT / Futures API의 `symbol=NAS100_USDT`. 매 API 호출 이전에 **`GET /api/v1/contract/detail`**에서 실제 지원 여부·거래상태·계약 사양을 확인한다.
- **REST 스냅샷:** MEXC 공식 [Get Ticker](https://www.mexc.io/api-docs/futures/market-endpoints/get-ticker-contract-market-data)는 `GET /api/v1/contract/ticker`를 문서화한다. 2026년 Futures API의 신규 도메인은 **`https://api.mexc.com`** ([공식 도메인 변경 공지](https://www.mexc.co/en-GB/announcements/article/futures-api-access-domain-update-17827791532974)). 아래는 **공식 엔드포인트에 기반한 요청 예시**이고, 본 검토에서 응답 내용을 직접 실행 검증하지 않았다.

```http
GET https://api.mexc.com/api/v1/contract/detail
GET https://api.mexc.com/api/v1/contract/ticker?symbol=NAS100_USDT
```

- **WebSocket**: 공식 [Futures WebSocket 프로토콜 및 Protobuf 가이드](https://www.mexc.com/api-docs/futures/websocket-api/protocol-buffers-integration/)에서 `sub.ticker` 등 시장 데이터 구독을 지원한다. 운영에서는 해당 문서에 명시된 WS 연결 주소, 구독 요청, 메시지 스키마와 heartbeat를 실제 세션으로 테스트하고 확정한다. **본 문서에 미검증 고정 WS URL·JSON 메시지 구조를 하드코딩하지 않는다.**
- **중요한 변경 예정:** [MEXC Futures WebSocket JSON→Protobuf 전환 공지](https://www.mexc.com/pt-BR/announcements/article/mexc-to-migrate-futures-websocket-market-data-from-json-to-protobuf-17827791539697)에 따른 **2026-12-01 10:00 UTC 마이그레이션 마감**. 신규 수집기는 **Protobuf 대응을 기본 계획**으로 하고 [공식 스키마 저장소](https://github.com/mexcdevelop/websocket-future-proto/)를 확인한다. **Spot WebSocket 규칙/마감과 혼동하지 않는다.**
- **거래시간**: [상품 상장 안내](https://www.mexc.com/announcements/article/mexc-to-launch-stock-index-futures-starting-with-nas100-us30-sp500-usdt-m-pairs-on-jan-29-17827791533334)에 거래 세션 및 일일 중단이 안내된다. **24시간 365일 연속 거래를 가정하지 않는다**. 미국 DST·휴장·거래소 공지 변경은 매번 확인한다.
- **지연 측정**: 원본 메시지의 이벤트시각, 클라이언트 수신시각, 현재 상품시장 상태로 *end-to-end delay*를 측정한 후 `real_time_observed` 표기를 결정한다. WS 연결 여부만으로 0초 지연이라 말하지 않는다.

## Binance: QQQ ETF 연계 저지연 보조 신호

- **2026-04-06 QQQUSDT 영구선물 상장:** [Binance 공식 공지](https://www.binance.com/en-IN/support/announcement/detail/4cde981dc32d4268b7645e9d16e8d63a).
- **원자산 정의:** Binance [ETF 관련 계약 설명](https://www.binance.com/en/academy/articles/etf-contracts-you-can-trade-on-binance-futures)은 QQQUSDT가 Invesco QQQ Trust Series 1 ETF를 추종함을 설명한다. **Nasdaq-100 지수 포인트, CME NQ, MEXC NAS100 영구선물과 같지 않음**.
- **기술 후보:** 기존 Auto-Axe Binance USDⓈ-M 선물 `/fapi/v1/exchangeInfo`, `/fapi/v1/ticker/price?symbol=QQQUSDT`, `wss://fstream.binance.com/market/stream?streams=qqqusdt@aggTrade`. **예시 경로는 기존 수집기에서 사용하는 2026년 시장 데이터 라우팅 규칙을 적용한 것이며 QQQUSDT의 실제 실시간 WS 수신은 미검증**이다.
- 기존 BTC/원자재와 다른 `instrument_type=qqq_etf_linked_perpetual`, `quote_currency=USDT`를 반드시 저장한다.

## Yahoo Finance / CME NQ: 지연된 실제 선물 비교값

- Yahoo [`NQ=F`](https://finance.yahoo.com/quote/NQ%3DF/) 페이지는 **CME - Delayed Quote**로 표시한다. 관측된 월물(예: 2026년 12월물)이 다음 분기로 롤오버될 수 있으므로 **계약월, 시리즈 변경 및 연속 시계열의 롤/백어드저스트 정책**을 별도 기록한다.
- `yfinance` 예시(무료 API 라이브러리; **실제 NQ 실시간 피드 아님**):

```python
import yfinance as yf
bars = yf.Ticker("NQ=F").history(period="1d", interval="1m")
print(bars.tail())
```

- 거래소별 지연 수준과 1분봉 가용 범위는 시점별로 재측정한다. `NQ=F`의 `WebSocket` 무지연 수신은 검증하지 않았다.
- CME 실제 NQ/MNQ 실시간 가격이 필수이면 **정식 데이터 권한을 보유한 중개사·거래소 피드**가 필요하며, 무료 웹페이지의 지연 표기를 우회하거나 다른 계약 가격을 원본으로 위장하지 않는다.

## Auto-Axe 수집 설계

```text
MEXC NAS100_USDT Futures WS (candidate, primary)
    └── stream: price + event_time + received_time + connection_state
Binance QQQUSDT Futures WS (candidate, secondary)
    └── stream: price + event_time + received_time + connection_state
Yahoo yfinance NQ=F delayed 1m candles (comparison)
    └── bar: OHLCV + bar_timestamp + observed_time + roll_metadata
                      ↓
                 Normalize & Store
     ├── NASDAQ100_MEXC_PERP_USDT
     ├── NASDAQ100_BINANCE_QQQ_PERP_USDT
     └── NASDAQ100_CME_NQ_YAHOO_DELAYED
```

필수 저장 필드: `series_id`, `provider`, `native_symbol`, `exchange`, `instrument_type`, `underlying_reference`, `quote_currency`, `contract_kind`, `source_event_at`, `received_at`, `event_age_ms`(유효 이벤트시각이 있을 때만), `market_session`, `data_status`(`live_observed|delayed|stale|no_trade|unverified`), `volume` 및 `source_url`.

**실행 전 검증 체크:**
1. MEXC `contract/detail`에서 `NAS100_USDT` 거래 가능 여부와 거래 세션 확인
2. MEXC ticker REST 응답 스키마·상태코드, WebSocket 실제 구독 성공·Protobuf 디코딩 검증
3. Binance `QQQUSDT` exchangeInfo/WS 실체결 테스트 및 USDT 호가 단위 확인
4. Yahoo `NQ=F` 데이터 시차 측정, 계약 교체·공식 CME 시간과 비교
5. 재연결·유휴 시간·백필·Rate Limit·재사용 라이선스 검토 및 원본별 별도 적재

**구현 상태 (2026-11-23):** **데이터 소스 조사/문서 반영만 완료**. `docs/examples/realtime_collector.py`에는 아직 NAS100/QQQ/NQ 수집 명령이 없다. 사용자 승인 없는 주문/거래 기능도 추가하지 않았다.

관련 문서: [전체 지표 출처](./Indicator_Data_Sources.md) · [무료 수집 카탈로그](./Free_Data_Collection.md) · [실시간 데이터 소스](./Real_Time_Data_Sources.md) · [수집기 설계](./Collector_Design.md).
