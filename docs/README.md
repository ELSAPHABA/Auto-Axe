# Auto-Axe — 무료 시장지표 수집 설계

> 2026-11-22 · NH나무 OpenAPI 퀀트 플랫폼의 외부 지표 수집 가이드. **유료 데이터 구독은 제외**한다.

## 수집 우선순위

1. **Yahoo Finance/yfinance가 제공하는 가격·시장지표는 yfinance 우선** (시장별 지연/라이선스 점검). 실시간 무지연을 보장하지 않으며 분봉/일봉 조회를 기본으로 한다.
2. 동일한 값의 yfinance 심볼이 없거나 실적·정책발표·일정처럼 구조상 해당하지 않는 항목은 **무료 공식 API·WebSocket·RSS·ICS·CSV** 사용.
3. API가 없으면 **사이트 약관상 허용된 HTML 수집**, 불가능하면 **수동 기록**.
4. 가격 *현물·선물*, 채권 *공식 파 수익률·Yahoo 금리지표*, 경제지표 *예정·실제·정정*은 별도 시계열.

## 미국 국채 지표 — 요청한 5개 만기

| 만기 | Auto-Axe 시리즈 | 기본 소스 | 심볼/필드 |
|---|---|---|---|
| **3개월** | `UST_3M` | yfinance | `^IRX` (13-week yield index) |
| **2년** | `UST_2Y` | US Treasury 무료 XML | `BC_2YEAR` |
| **5년** | `UST_5Y` | yfinance | `^FVX` |
| **10년** | `UST_10Y` | yfinance | `^TNX` |
| **30년** | `UST_30Y` | yfinance | `^TYX` |

**2년 금리 선물 `2YY=F`·`ZT=F`는 2년 국채 현물 수익률이 아니므로 대체하지 않는다.** Treasury에서 5개 만기의 동일 정의 공식 일별 값을 교차 검증용으로 추가 확보할 수 있다.

## 주요 시세·지표

| 지표 | 기본 수집 | 비고 |
|---|---|---|
| VIX | yfinance `^VIX` | Cboe EOD 검증, 지연 가능 |
| WTI | yfinance `CL=F` | NYMEX **선물**, EIA WTI 현물 일별 별도 |
| Brent | yfinance `BZ=F` | NYMEX **Brent Financial 선물**, ICE 원계약과 다름 |
| 금 선물 | yfinance `GC=F` | COMEX 선물; 금 현물은 기존 Gold API 유지 |
| 비트코인 | yfinance `BTC-USD` | 거래소 원본 틱은 Coinbase/Binance 무료 WS 선택 |
| CNN 공포·탐욕 | [CNN International](https://edition.cnn.com/markets/fear-and-greed) | 약관상 허가 전 수동 |
| 피자지수 | [PizzINT](https://www.pizzint.watch/) | 공개 JSON 확인, robots/약관 권한 확인 전 수동 |
| 가이던스·경제발표·파생 만기·정책금리 | SEC·BLS·BEA·OCC·중앙은행 공개 자료 | 공식 원본 이벤트·시계열 |

## 실행

```bash
python -m pip install -r docs/examples/requirements.txt
python docs/examples/realtime_collector.py yf-market --period 1d --bar-interval 1m
python docs/examples/realtime_collector.py treasury-five
python docs/examples/realtime_collector.py gold --interval 60
```

- [YFinance_First_Collection.md](./YFinance_First_Collection.md): **최신 기본 소스·5종 국채 만기 명세** 및 명령/주의사항
- [Free_Data_Collection.md](./Free_Data_Collection.md): 전체 무료 지표 및 스크래핑·수동 대체 정책
- [Realtime_Quickstart.md](./Realtime_Quickstart.md): 실제 설치·실행·API 사용 설명
- [YFinance_Data_Validation.md](./YFinance_Data_Validation.md): 지원 심볼 및 과거 실측 테스트
- [Manual_Collection.md](./Manual_Collection.md): 허가되지 않은 웹 추출·데이터 부재 시 수동 기록 방법
- [Collector_Design.md](./Collector_Design.md): 스키마·시각·백테스트·장애 처리 설계
- [examples/realtime_collector.py](./examples/realtime_collector.py): 수집기 · [examples/yfinance_probe.py](./examples/yfinance_probe.py): 테스트 전용 · [examples/manual_record.py](./examples/manual_record.py): 수동 기록

> **실제 사용 유의:** Yahoo의 분봉/WS 지원은 해당 심볼의 무지연 실시간성과 자동매매·재배포 권한을 입증하지 않는다. 무료/개인 연구용 데이터의 라이선스 조건을 확인하고 운영 경계를 정한다. 이 저장소의 예제는 데이터 수집 PoC이며 매매 주문 기능을 변경하지 않는다.


## Binance API 커버리지 (2026-11-23 직접 검사)

- **Binance 공개 시장 API의 Auto-Axe 직접/관련 시세 범위: 4개 분야** — BTC Spot `BTCUSDT` / `BTCUSDC`, 금 관련 `PAXGUSDT`·`XAUTUSDT` 및 `XAUUSDT`, WTI 관련 영구선물 `CLUSDT`, Brent 관련 영구선물 `BZUSDT`.
- **2개 분야는 간접 ETF 연동 상품만** — VIX 관련 `UVXYUSDT`, 미국 장기국채 ETF 관련 `TMFUSDT`·`TBTUSDT`. **원본 VIX 지수·미국 국채 3M/2Y/5Y/10Y/30Y 수익률은 Binance가 직접 제공하지 않음.**
- **1개 분야 부분 지원** — Binance 자체 암호화폐·금 옵션의 계약·만기정보 `eapi/v1/exchangeInfo`; 미국 주식·옵션 거래소 전체 만기정보가 아님.
- 나머지 기업 가이던스·경제지표·중앙은행 금리·CNN 공탐·PizzINT 피자 수치는 Binance 시세 API 지원 대상이 아님.

[Binance API 실제 조사](./Binance_API_Coverage.md) · [Binance 무료 공개 API 검증 코드](./examples/binance_coverage_probe.py)

**수집 공급원 우선순위는 변경하지 않는다:** 기존 yfinance, 원기관 공공 데이터, 승인된 출처를 유지하며 Binance 자산 연동 영구선물은 별도 참고 시계열로만 사용한다.
