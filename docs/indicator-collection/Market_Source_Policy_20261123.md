# Auto-Axe 시장 데이터 소스 정책

## 1. 적용 범위

시장가격은 Binance 공개 체결 스트림을 기본으로 한다. VIX 및 국채 3M/5Y/10Y/30Y와 미국 주식·ETF의 지정 지표는 yfinance를 사용한다. 토스증권 `ROB.US2YT-RR` (`UST_2Y_TOSS`)을 15분 승인형 Scrapling Fetcher→DynamicSession 수집의 최우선 원본으로 지정한다. 최근 검수된 표시값이 없거나 수집 실패·권한 제한 시 미국 재무부 `BC_2YEAR` 일별값(`UST_2Y_TREASURY`)으로 임시 fallback한다. 원본 갱신 시각 미확인 토스값은 수집 시각과 구분한다. 2026-11-28 사용자 승인에 따라 독립 검수 및 현재 source trading grant를 충족한 최신 관측값은 개인 자동매매 판단에 사용할 수 있다. 제3자 재배포는 금지한다. 960초 수집 시각 유효성은 원본 시세 TTL이 아니며, 원본 시각이 필수인 Workflow는 UNKNOWN 처리한다. 원본 시계열과 전환 이력을 분리하며 기존 네이버 관측값은 변경하지 않는다.

## 2. 대상별 기본 데이터 소스

### 2026-11-27 사용자 확정 수집 정책 (기존과 충돌 시 우선)

- SMA/EMA 및 5/10/20거래일 고저가의 OHLCV는 로컬 우선(Cache-first). 필요한 유효 확정봉·EMA 초기화 이력이 로컬에 있으면 외부 요청 0회, 없거나 불완전하면 부족한 거래세션 구간만 Yahoo HTTP 요청 후 로컬 원장과 병합하여 계산한다. [상세](./YFinance_Valuation_and_Moving_Averages.md#4-auto-axe-수집계산-주기).

- VIX는 반드시 원본 이벤트 기준 TTL 10초 및 허용 범위 내 즉시 갱신. 원본 지연/미수신은 stale 또는 UNKNOWN으로 처리하고 TTL을 늘리거나 수신시각으로 대체하지 않는다. VIX는 필수 신선도 요구사항이며 공급자 제약으로 충족하지 못하면 신호 차단, 별도 검증 필요.
- 미국 국채 3M/5Y/10Y/30Y는 yfinance 정기 조회 900초(15분). 기존 원본 TTL 300초는 조회 주기와 구분해 유지하며, 오래된 관측을 15분 동안 최신으로 간주하지 않는다. 2Y Toss 우선/Treasury 일별 임시 fallback은 그대로 유지.
- WTI/Brent는 각각 Binance WS CLUSDT/BZUSDT를 최우선으로, 해당 스트림 실패 시에만 Yahoo WS CL=F/BZ=F fallback. Binance 정상 복구 시 우선 원본으로 복귀하고 사유·시각·원본을 기록한다. 정규 휴장과 장애를 구분한다. Yahoo USD 만기선물과 Binance USDT 연동 영구선물은 별도 series, 상품·단위·계약·지연을 표시하고 전환 경계 수익률/EDGE/rolling은 UNKNOWN 또는 재기준화. Yahoo WS 실제 심볼 수신 검증 전 fallback을 가동하지 않는다.
- NVDA/QLD WS day_volume 로컬 1Hz 기록, 후행/예상 PER·PBR 일별, ROE 실적 발표 후, 확정 OHLCV 기반 SMA 5/20/60/120/200 및 EMA 12/26, 최근 5/10/20 실제 거래 세션 고저가를 유지한다. ETF 기업 재무비율은 결측. NQ=F 지연 1분봉 비교도 유지.
- yfinance HTTP 구현은 기존 명세대로 복원하는 방향으로 확정한다. 최초 과거 OHLCV 일괄 확보 후 증분 수집(일봉 확정 후 거래일 1회, 정정·분할·배당 및 워밍업 보존), 캐시·single-flight·bounded request/concurrency/timeout, 429 Retry-After/backoff 및 403 중단, UI refresh와 정기 외부 호출 분리. 내부 재시도/쿠키 요청 포함 실제 호출량 제어 검증 필요. 개인·연구·교육·비영리, 제3자 재배포 금지 및 기존 권한 게이트 유지. 개발 구현과 공급자 운영 허용 여부는 별개.

현재 구현 상태 (2026-11-28): 국채 정기 조회 스케줄 900초, VIX TTL 10초 유지. Yahoo HTTP의 승인형 transport 및 cache-first 일봉 병합, VIX 내부 즉시 갱신/전용 WS runner, 원유 독립 WS fallback 및 공급원 표시를 구현했다. Binance 원유 WS 실제 임시 PG17 저장 17건 성공. Yahoo 자동 호출에 대한 명시적 공급자 권한 및 원본 계약/지연 검증 미확보로 실제 Yahoo HTTP/WS 호출과 VALID 승격은 미실행. 운영 배포 및 조건 엔진 연결은 별도 단계다.

| 지표 | 기본 공급원 | 내부 식별자 | 정확한 상품 정의 |
|---|---|---|---|
| 금 가격 동향 | **Binance Futures WS** `XAUUSDT@aggTrade` | `GOLD_BINANCE_PERP` | Binance TradFi 금 연동 영구선물 **USDT 기준** |
| 은 가격 동향 | **Binance Futures WS** `XAGUSDT@aggTrade` | `SILVER_BINANCE_PERP` | 은 연동 USDT 영구선물 |
| 구리 가격 동향 | **Binance Futures WS** `COPPERUSDT@aggTrade` | `COPPER_BINANCE_PERP` | 구리 연동 USDT 영구선물 |
| WTI 가격 동향 | **Binance Futures WS** `CLUSDT@aggTrade`; 실패 시 Yahoo WS `CL=F` | `WTI_BINANCE_PERP`; Yahoo 별도 시계열 | Binance 원유 연동 영구선물 USDT / Yahoo USD 만기선물, fallback 미검증 |
| Brent 가격 동향 | **Binance Futures WS** `BZUSDT@aggTrade`; 실패 시 Yahoo WS `BZ=F` | `BRENT_BINANCE_PERP`; Yahoo 별도 시계열 | Binance Brent 연동 영구선물 USDT / Yahoo USD 만기선물, fallback 미검증 |
| 비트코인 | **Binance Spot WS** `BTCUSDT@trade` | `BITCOIN_BINANCE_SPOT` | Binance BTC/USDT 현물 **USDT 기준** |
| 미국 개별주식 PER·PBR·ROE | **yfinance `Ticker.info` 후행/예상 PER·PBR·ROE 스냅샷** | `EQUITY_PER_TTM`, `EQUITY_PER_FORWARD`, `EQUITY_PBR`, `EQUITY_ROE` | 일별/실적 갱신시점 분리, ETF 결측 기본. [명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 이동평균선(SMA·EMA) | **yfinance OHLCV로 로컬 산출** | `SMA_N`, `EMA_N` + interval | 확정 일봉/분봉 기준, 조정종가·워밍업 및 백테스트 시점 보존. [명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 최근 5·10·20거래일 최고·최저가 | **yfinance `High`·`Low` 일봉 → rolling 최댓값·최솟값 로컬 계산** | `HIGH_5D/10D/20D`, `LOW_5D/10D/20D` | 실제 거래 세션 N개 기준. 일봉 확정 후 당일 포함, 장중 비교는 직전 N개 확정봉 기준. [명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 미국 주식·ETF 초단위 누적 거래량 (NVDA·QLD 등) | **yfinance WebSocket `day_volume` + 로컬 1초 주기 스냅샷** | `US_STOCK_DAILY_CUM_VOLUME_1S` + symbol | 원본 WS 이벤트 주기는 불규칙, 새 값 없으면 `stale/no_update`로 직전 값 표시; 진정한 무지연 초봉 또는 SIP 통합 체결량 아님. [명세](./YFinance_1s_Stock_Cumulative_Volume.md) |
| 나스닥 100 선물·연동 신호 | **MEXC `NAS100_USDT` 무료 Futures WebSocket(개발/검증 후보)**; Binance `QQQUSDT` 별도 보조, yfinance `NQ=F` 지연 CME 기준 | `NASDAQ100_MEXC_PERP_USDT` / 별도 2시리즈 | MEXC는 지수 연동 영구선물, Binance는 QQQ ETF 연동 계약, Yahoo는 CME 실제 NQ 지연 시세. WS 수신 미검증; [조사 문서](./Nasdaq100_Futures_Data_Sources.md) |
| VIX | yfinance `^VIX` | `VIX` | Cboe VIX 지수, 원본 기준 TTL 10초; 지연 가능 |
| 미국 국채 3개월 | yfinance `^IRX` | `UST_3M` | Yahoo 13주물 금리지표 |
| 미국 국채 2년 | **토스증권 `ROB.US2YT-RR` 최우선; 실패/실행 불가 시에만 Treasury `BC_2YEAR` 임시 일별 fallback** | `UST_2Y` (논리); `UST_2Y_TOSS` / `UST_2Y_TREASURY` (원본) | 토스증권 게시 수익률 및 Treasury 공식 par yield를 별도 유지 |
| 미국 국채 5년 | yfinance `^FVX` | `UST_5Y` | Yahoo 5년물 금리지표 |
| 미국 국채 10년 | yfinance `^TNX` | `UST_10Y` | Yahoo 10년물 금리지표 |
| 미국 국채 30년 | yfinance `^TYX` | `UST_30Y` | Yahoo 30년물 금리지표 |

- Binance **실시간**은 **해당 Binance 계약/현물 시장의 최신 거래 이벤트**라는 뜻이다. 현물 금(XAU/USD)이나 CME 금·원유 선물 자체의 틱을 대체할 수 없다. 스트림 연결 성공 ≠ 지연 0 검증.
- Binance 원유·금 TradFi 계약은 거래시간·휴장·유동성 제한이 있을 수 있다. 이벤트 수신이 없을 때는 최신 시각만으로 시장이 열렸다고 간주하지 않는다.
- Binance `USDT` 호가를 `USD` 호가나 USD 현물 벤치마크로 환산 없이 합치지 않는다.
- 기존 현물 원본값이 필요한 경우 **Gold API 현물 참고값**(별도 `gold-spot-reference`), **EIA WTI/Brent 일별 현물**, **Treasury 공식 5개 만기 일별**, **Cboe VIX EOD**를 원본 시계열로 *분리*한다.
- **두바이유는 수집 대상에서 제외**되어 있다.

## 3. 국채 2년물 수집 및 검증 근거

토스증권 `ROB.US2YT-RR` (`UST_2Y_TOSS`)을 15분 승인형 Scrapling Fetcher→DynamicSession 수집의 최우선 원본으로 지정한다. 최근 검수된 표시값이 없거나 수집 실패·권한 제한 시 미국 재무부 `BC_2YEAR` 일별값(`UST_2Y_TREASURY`)으로 임시 fallback한다. 원본 갱신 시각 미확인 토스값은 수집 시각과 구분한다. 2026-11-28 사용자 승인에 따라 독립 검수 및 현재 source trading grant를 충족한 최신 관측값은 개인 자동매매 판단에 사용할 수 있다. 제3자 재배포는 금지한다. 960초 수집 시각 유효성은 원본 시세 TTL이 아니며, 원본 시각이 필수인 Workflow는 UNKNOWN 처리한다. 원본 시계열과 전환 이력을 분리하며 기존 네이버 관측값은 변경하지 않는다.

전환 후 일별 Treasury 값은 별도 원본과 freshness를 유지한다. 실거래 Workflow는 원본 고정 기본이며 명시적 fallback 허용 및 품질 검증 없이는 UNKNOWN. [공통 시계열 계약](../tech-stack/data-storage.md) · [신선도](../tech-stack/data-collection.md).

원본 페이지: [토스증권 2년물](https://www.tossinvest.com/indices/ROB.US2YT-RR).

2026-11-28 사용자 승인 및 단발 검증: robots.txt 대상 경로 허용, HTTP 200 정적 HTML에는 수익률 미포함. 정상 Chrome/Playwright 렌더링 후 미국 채권 목록의 정확한 2년물 행을 확인했다. 숫자 표시 애니메이션 및 전일 대비 변동률을 수익률로 혼동하지 않는다. 원본 시세 갱신 시각은 미확인이다. 독립 source/adapter grant와 검수 전 승격 금지. 수집 시각은 원본 시각이 아니며 공급자 약관 전문 및 원천 라이선스 별도 검토. 기존 Naver 2026-11-23 조사 기록은 Git 이력에 보존한다.

## 4. 수집 PoC 실행

```bash
python -m pip install -r docs/examples/requirements.txt
# Binance 시장에서 실제 틱이 발생하면 즉시 출력, 끊어지면 백오프 재연결
python docs/examples/realtime_collector.py binance-live
# Binance 선물 REST 마지막 가격 단발 조회
python docs/examples/realtime_collector.py binance-futures
# 금 연동 영구선물 단발 조회(기존 gold 명령 호환)
python docs/examples/realtime_collector.py gold
# 금 현물 참고 지표는 별도이며 기본 실시간 시세로 사용하지 않음
python docs/examples/realtime_collector.py gold-spot-reference
# Binance가 해당 원본을 제공하지 않는 지표만 yfinance
python docs/examples/realtime_collector.py yf-market
# 공식 2년물 일별 fallback/5개 만기 전체 검증
python docs/examples/realtime_collector.py treasury-five
```

`binance-live`는 Binance Spot `BTCUSDT@trade` 및 Futures `XAUUSDT/XAGUSDT/COPPERUSDT/CLUSDT/BZUSDT@aggTrade`를 **동시 처리**, WebSocket 재연결 및 트레이드 ID·거래량·타임스탬프 보존. 실운영에는 거래 시간 정책 확인, 누락 구간 REST 백필, 연결 상태 감지, 레이트 리밋 준수가 추가 필요하다.

## 5. 거래 통계

Binance 공식 롱숏 4종(전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율)은 BTCUSDT 선물 및 금·은·구리·WTI·Brent 연동 선물의 `/futures/data/*` 공개 REST 최소 5분 집계로 수집한다. BTC 가격은 Spot, 비율은 Futures로 별도 표기한다. Taker 거래량 비율은 포지션 비율이 아니며 WS 실시간 틱으로 표시하지 않는다. [API·실측 및 실행 명세](./Binance_Metals_LongShort_20261123.md).

```bash
python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300
```

## 6. 출처

- [Binance Spot market-data documentation](https://developers.binance.com/en/docs/products/spot/web-socket-streams)
- [Binance USDⓈ-M Futures market streams](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction)
- [Binance API 검증 및 관련 계약 차이](./Binance_API_Coverage.md)
- [토스증권 원본 2년물](https://www.tossinvest.com/indices/ROB.US2YT-RR)
- [U.S. Treasury 공식 일별 수익률 XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
