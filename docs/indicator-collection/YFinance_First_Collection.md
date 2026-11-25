> **변경 공지 (2026-11-23): 이 문서의 yfinance 우선 가격 수집 전략은 이전 설계 이력입니다.** 최신 기본은 [Binance 실시간·네이버 2Y 소스 정책](./Market_Source_Policy_20261123.md)입니다. 금·WTI·Brent·BTC의 yfinance 가격 기본 수집은 중단되고, yfinance는 VIX 및 국채 3M/5Y/10Y/30Y만 담당합니다. 미국 국채 2Y는 네이버 증권에서 담당합니다.

# Auto-Axe yfinance 우선 시장지표 수집 명세 (2026-11-22 이전 설계 기록)

> 2026-11-22 기준. **시세·지수·채권금리지표 중 Yahoo Finance/yfinance에서 제공하는 것은 yfinance가 우선**이다. **무료** 수집만 사용하며, 공식 원본 값/경제 이벤트/정책금리는 해당 기관의 무료 API를 유지한다.

## 기본 채권 만기 5종 (필수)

| 만기 | 내부 series_id | 기본 수집 | 심볼/원본 필드 | 특징 |
|---|---|---|---|---|
| 3개월 | `UST_3M` | **yfinance** | `^IRX` | Yahoo의 13-week T-bill 수익률 관련 **지표** |
| 2년 | `UST_2Y` | **미국 재무부 공식 무료 XML** | `BC_2YEAR` | 정확한 2Y 현물 파 수익률용 Yahoo/yfinance 심볼 검증 실패 |
| 5년 | `UST_5Y` | **yfinance** | `^FVX` | Yahoo 5Y 국채 수익률 지표 |
| 10년 | `UST_10Y` | **yfinance** | `^TNX` | Yahoo 10Y 국채 수익률 지표 |
| 30년 | `UST_30Y` | **yfinance** | `^TYX` | Yahoo 30Y 국채 수익률 지표 |

- **2년물 주의**: Yahoo `2YY=F` (2-Year Yield Futures)와 `ZT=F` (2-Year T-Note Futures)는 조회되지만 **2년 만기 국채 수익률 그 자체가 아니라 선물상품**이다. `^UST2Y`, `^US2Y`, `US2Y` 등은 2026-11-22 Yahoo chart에서 404 확인. 따라서 `2Y`는 절대로 선물값으로 대체하지 않는다.
- **교차 검증**: 공식 Treasury [Daily Treasury Par Yield Curve XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)에서 `BC_3MONTH`, `BC_2YEAR`, `BC_5YEAR`, `BC_10YEAR`, `BC_30YEAR`를 모두 일별로 받을 수 있다. Yahoo 지수값과 정의·시각·스케일이 다를 수 있으므로 **같은 출처의 5개 만기 공식 수익률곡선을 별도 저장**한 뒤 왜곡 없이 비교하는 것을 권장한다.
- 3개월물 `^IRX`은 **13주물**로 통상 3개월물로 분류하지만 Treasury `BC_3MONTH`와 원천·계산법이 완전히 같다는 보장은 없다.
- 3M·5Y·10Y·30Y의 yfinance 1분봉 가용성이 모두 같거나 실시간 무지연임을 의미하지 않는다. `2Y` 공식 값은 **일별 갱신**한다.

## 가격·지수에서 yfinance 기본 사용

| 지표 | 내부 series_id | 우선 공급자 | 종목 | 기준 / 수집 유의 |
|---|---|---|---|---|
| VIX | `VIX` | **yfinance** | `^VIX` | Yahoo Cboe VIX 지수, 거래소 데이터 지연 확인 |
| WTI 원유 | `WTI_FUTURE` | **yfinance** | `CL=F` | **NYMEX WTI 선물** (EIA 일별 *현물*과 다름) |
| Brent 원유 | `BRENT_FUTURE` | **yfinance** | `BZ=F` | **NYMEX Brent Last Day Financial Futures** (ICE 원계약과 다름) |
| 금 선물 | `GOLD_FUTURE` | **yfinance** | `GC=F` | **COMEX 금 선물**, USD/troy oz, 무료·지연 가능 |
| 비트코인 USD | `BITCOIN` | **yfinance** | `BTC-USD` | Yahoo 집계 시세, 거래소 공식 체결가와 별개 |
| 금 현물가 | `XAUUSD.spot_estimate` | **Gold API** | `/price/XAU` | `GC=F` 선물로 현물가격을 덮어쓰지 않는다 |

추가로 `GC=F`는 금선물 *보조 지표*로 수집하고 현물 금값 `XAU/USD`의 기본 공급원은 그대로 유지한다. `BTC-USD`는 yfinance를 표준 시장 **요약 시세**로 삼되 실제 Coinbase/Binance 거래소 체결 틱의 무료 WebSocket은 추가로 활성화할 수 있다. `BTCUSDT`와 `BTC-USD`를 같은 값으로 병합하지 않는다.

**원유 현물의 일별 확정 가격**은 EIA 무료 API `PET.RWTC.D` (WTI), `PET.RBRTE.D` (Brent)를 별도 저장할 수 있다. 선물과 spot의 시계열 키/차트 라벨을 반드시 분리한다.

## yfinance를 적용하지 않는 지표

- **CNN 공탐지수**: [edition.cnn.com](https://edition.cnn.com/markets/fear-and-greed) 원본을 수동 기록. Yahoo/yfinance 대응 원본 점수 심볼 없음;
- **PizzINT 피자지수**: [pizzint.watch](https://www.pizzint.watch/) 지정 출처; `/api/dashboard-data` 응답 확인. Yahoo/yfinance에서 동일 원본 수치 제공 안 함.
- **기업 가이던스**: SEC EDGAR 8-K/기업 IR RSS; Yahoo 금융 실적 추정값과 기업 자체 forward guidance 혼동 금지.
- **경제지표 발표·실제값**: BLS·BEA·Fed/중앙은행의 공식 무료 ICS·RSS·JSON/HTML 원문.
- **파생 만기 달력**: OCC·CME 공식 공개 캘린더; Yahoo의 선물 quote만으로 상품별 실제 만기 확정 불가.
- **미·일·영·유로존 기준금리**: FOMC·BOJ·BoE·ECB 공식 성명과 무료 시계열. Yahoo 채권금리지표를 중앙은행 기준금리로 대체하지 않음.

## 설치 및 즉시 실행

```bash
python -m pip install -r docs/examples/requirements.txt

# yfinance 지원 전체 지표: VIX, 3M/5Y/10Y/30Y, WTI/Brent 선물, 금 선물, BTC-USD
python docs/examples/realtime_collector.py yf-market --period 1d --bar-interval 1m

# 요청한 국채 만기 3M·2Y·5Y·10Y·30Y 공식 일별 교차검증 (2Y 필수)
python docs/examples/realtime_collector.py treasury-five

# 개별 조회
python docs/examples/realtime_collector.py yf-market --symbols VIX UST_10Y UST_30Y --bar-interval 1m
python docs/examples/realtime_collector.py yf-market --symbols WTI_FUTURE BRENT_FUTURE --period 5d --bar-interval 1d

# 정확한 금 현물 (선물과 별도)
python docs/examples/realtime_collector.py gold --interval 60
```

`yf-market`는 수신한 각 종목의 **최신 조회 가능한 캔들**을 JSONL 한 행으로 출력한다. `--interval 60`을 지정하면 60초마다 재조회하지만 Yahoo 데이터가 60초 이내에 새로 게시되거나 지연이 없다는 보증은 없다. 기본 정규화 필드 `provider`, `series`, `symbol`, `instrument_type`, `source_event_at`, `received_at`, `unit`, `exchange_delay_minutes`, `status=potentially_delayed`을 반드시 유지한다.

## 백테스트와 신뢰도

1. yfinance가 지원하는 시계열도 각 종목별 **시장 운영시간, 최신바 시각, 제공 지연, 빈봉, 서머타임**을 측정한다.
2. **금 현물(spot)과 선물, 원유 현물과 선물, Treasury 공식 par yield와 Yahoo Cboe 금리지표는 서로 다른 시리즈**로 유지한다.
3. yfinance 공식 WebSocket 클래스는 있지만 실제 `^IRX,^FVX,^TNX,^TYX,^VIX,CL=F,BZ=F`의 WS 이벤트 전달 및 무지연 업데이트를 확인하지 못했다. **기본은 `Ticker.history` 폴링**, WebSocket은 [진단 예제](../examples/yfinance_probe.py)로만 검증한다.
4. Yahoo/yfinance는 [개인·연구용 이용 제한](https://github.com/ranaroussi/yfinance)과 Yahoo의 콘텐츠 이용권 문제가 있어 **자동매매와 외부 재배포**에 사용하기 전 관련 약관을 반드시 확인한다.
5. **2년물 fallback 없음**: 무료 Treasury feed 장애 시 결측·지연으로 표시한다. 2년 금리 선물을 공식 현물 수익률로 위장하지 않는다.

관련 문서: [무료 소스 마스터](./Free_Data_Collection.md) · [실행 가이드](./Realtime_Quickstart.md) · [기존 yfinance 실증](./YFinance_Data_Validation.md).
