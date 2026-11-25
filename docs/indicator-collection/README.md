# Auto-Axe — 무료 시장 데이터 수집 설계

> 무료 데이터만 수집한다. 원자산·계약 종류·시각·권한을 구분한다. 저장소의 코드는 수집 PoC이며 운영 수집기 및 주문 기능은 미구현이다.

## 수집 정책

네이버 증권 `US2YT=RR`을 최우선 원본(`UST_2Y_NAVER`)으로 지정한다. 스크래핑 실패로 실행할 수 없는 경우에만 미국 재무부 `BC_2YEAR` 일별값(`UST_2Y_TREASURY`)을 임시 fallback으로 표시한다. 네이버 정상 수집 복구 즉시 우선 원본으로 복귀하고 전환 사유·시각·원본을 기록한다. 원본별 데이터 정의·시각·신선도를 분리하고 일별 fallback을 장중 실시간 수익률로 사용하지 않는다.

VIX 원본 TTL은 10초이며 [전체 신선도 표준](../tech-stack/data-collection.md)을 적용한다.

- **가격·체결 데이터:** Binance 무료 **WebSocket 우선** — 금·은·구리 연동 영구선물 `XAUUSDT`, `XAGUSDT`, `COPPERUSDT`, WTI 연동 영구선물 `CLUSDT`, Brent 연동 영구선물 `BZUSDT`, 비트코인 현물 `BTCUSDT`. REST로도 최근 가격을 조회할 수 있다. *수신 틱이 존재할 때만* 거래소 실시간 체결이고, 거래소·계약 거래시간 밖에는 갱신되지 않는다.
- **VIX·국채 금리지표:** Binance에 동일한 원본이 없어 yfinance `^VIX`, `^IRX`, `^FVX`, `^TNX`, `^TYX` 유지 (지연 가능). **미국 2년물은 지정된 네이버 증권 페이지** [US2YT=RR](https://m.stock.naver.com/marketindex/bond/US2YT=RR)에서 값을 확인한다. 다만 `robots.txt`가 `Disallow: /`이므로 무허가 자동 수집은 비활성화; 실패/실행 불가 시에만 Treasury 공식 일별 수익률로 임시 fallback하고 정상 복구 시 복귀.
- **경제지표·정책·기업 가이던스·만기일:** 공식 무료 API, 보도자료, RSS/Atom, ICS 우선. 허가받은 스크래핑 또는 수동 입력.
- **수집 대상에 두바이유는 없음.**

## 미국 국채 5개 만기

| 만기 | 기본 소스 | 표기/심볼 |
|---|---|---|
| 3개월 | yfinance 지표 | `^IRX` |
| 2년 | **네이버 증권 US2YT=RR (자동화 허가 필요)** | `US2YT=RR`; 실패/실행 불가 시 임시 Treasury 일별 `BC_2YEAR` |
| 5년 | yfinance 지표 | `^FVX` |
| 10년 | yfinance 지표 | `^TNX` |
| 30년 | yfinance 지표 | `^TYX` |

Yahoo 금리지표와 미국 재무부 공식 par yield는 다른 제공 체계다. 2년물 네이버 표시값은 원본 시간·지연표시를 저장하며 국채 금리선물·레버리지 ETF로 대체하지 않는다.

## 시장 가격 및 거래 통계

| 관심 항목 | Binance 우선 | 정확한 자산 유형 |
|---|---|---|
| 금 | `XAUUSDT` | USDT 표시 **금 연동 무기한 선물**, 금 현물 XAU/USD·COMEX `GC=F`와 다름 |
| 은 | `XAGUSDT` | USDT 표시 은 연동 영구선물 |
| 구리 | `COPPERUSDT` | USDT 표시 구리 연동 영구선물 |
| WTI | `CLUSDT` | Binance 원유 연동 무기한 선물, NYMEX `CL=F`와 다름 |
| Brent | `BZUSDT` | Binance 원유 연동 무기한 선물, NYMEX `BZ=F`와 다름 |
| 비트코인 | `BTCUSDT` | Binance Spot BTC/USDT, Yahoo BTC-USD와 호가통화 다름 |
| VIX | yfinance `^VIX` | Binance `UVXYUSDT`는 **다른 파생상품** |
| 국채 3M/5Y/10Y/30Y | yfinance 금리지표 | Binance `TMFUSDT`·`TBTUSDT`는 별개 장기채 레버리지·인버스 ETF 연동 계약 |

Binance 공식 롱숏 4종(전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율)은 BTCUSDT 선물 및 금·은·구리·WTI·Brent 연동 선물의 `/futures/data/*` 공개 REST 최소 5분 집계로 수집한다. BTC 가격은 Spot, 비율은 Futures로 별도 표기한다. Taker 거래량 비율은 포지션 비율이 아니며 WS 실시간 틱으로 표시하지 않는다. [API·실측 및 실행 명세](./Binance_Metals_LongShort_20261123.md).

금의 참고 **현물 추정가격**은 별도 `gold-spot-reference` 명령으로 Gold API를 사용할 수 있다. 기본 거래소 라이브 가격과 혼합하지 않는다.

## 빠른 실행

```bash
python -m pip install -r docs/examples/requirements.txt

# Binance 라이브 트레이드 스트림: 금·은·구리·WTI·Brent 영구선물 + BTC Spot
python docs/examples/realtime_collector.py binance-live

# Binance 연동 선물 최근 가격 REST 1회
python docs/examples/realtime_collector.py binance-futures

# Binance 선물 롱숏 4종
python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300

# VIX와 국채 3M/5Y/10Y/30Y: yfinance 지연 가능
python docs/examples/realtime_collector.py yf-market

# 2년물: 네이버 실패/실행 불가 시 임시 공식 Treasury 일별 값
python docs/examples/realtime_collector.py treasury-five

# 네이버: 승인을 받은 경우에만 AUTO_AXE_NAVER_SCRAPE_AUTHORIZED=1 설정
python docs/examples/realtime_collector.py naver-2y
```

## 문서

- [시장 데이터 소스 정책](./Market_Source_Policy_20261123.md) · [Binance API 직접 검증](./Binance_API_Coverage.md)
- [실행 가이드](./Realtime_Quickstart.md) · [전체 무료 데이터 카탈로그](./Free_Data_Collection.md) · [수집기 아키텍처](./Collector_Design.md)
- [yfinance 지원 검증](./YFinance_Data_Validation.md) · [yfinance 수집 적용 범위](./YFinance_First_Collection.md)
- [수동 기록 정책](./Manual_Collection.md) · [실행 코드](../examples/realtime_collector.py) · [스크래핑 권한 검증 예제](../examples/naver_bond_source_probe.py)

> Binance 무료 공개 시장데이터는 거래소의 공개 시세일 뿐, 다른 거래소의 무지연 가격 또는 현물 지표와 동일하다는 의미는 아니다. 해당 상품의 제공 지역 및 Binance 이용조건을 확인한다.

## 서학개미 해외주식 매수·매도 결제 통계

[한국예탁결제원 SEIBro 해외주식 종목별내역(주식TOP50)](https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921)을 수집 대상으로 한다. **미국 등 국가별·기간별 매수결제, 매도결제, 순매수결제(USD)**를 추적하는 결제 기반 통계다. **WebSquare 브라우저 스크래핑 대상으로 지정**. TOP50를 전체 서학개미 투자 총액으로 해석하지 않는다.

- [SEIBro 수집 필드·조회 옵션·권한 확인 명세](./SEIBro_Overseas_Stock_Flows.md)

## 나스닥 100 선물·연동상품 실시간 수집 후보

- **MEXC `NAS100_USDT`**: 공개 Futures WebSocket 저지연 시장 시세 후보. **CME NQ가 아닌 지수 연동 영구선물**이며 Protobuf 기반 WebSocket 전환 및 실측 지연 검증 필요.
- **Binance `QQQUSDT`**: QQQ ETF 연동 영구선물로 별도 참고 시계열.
- **Yahoo Finance `NQ=F`**: 실제 CME NQ 선물의 무료 **지연** 1분봉 비교값. 유료 CME 직접 실시간 피드는 기본 범위에서 제외.
- **문서 조사만 완료**, 실제 NAS100/QQQ WS 연결 및 Auto-Axe 수집기 구현은 아직 수행하지 않음. [데이터 소스·API·상세 검증 계획](./Nasdaq100_Futures_Data_Sources.md).

## 미국 주식·ETF 누적 거래량 1초 수집

**NVDA·QLD 등 미국 주식·ETF**는 `yfinance.AsyncWebSocket`의 `day_volume`(당일 누적 거래량)을 이용한다. WebSocket 메시지 수신 시 최신 누적값을 갱신하고, **로컬 스케줄러가 매초 그 값을 스냅샷**으로 기록한다. **Yahoo의 원본 메시지가 정확히 1초마다 도착하는 것은 아니며, 업데이트가 없을 때는 `stale/no_update` 표시**가 필요하다. 장중 실측 및 수집기 구현은 아직 수행하지 않았다.

- [yfinance WebSocket 1초 누적 거래량 상세 설계 및 Python 예제](./YFinance_1s_Stock_Cumulative_Volume.md)

## 기업 재무비율(PER·PBR·ROE)과 이동평균선

- **PER 후행/예상·PBR·ROE:** yfinance `Ticker.info`에서 `trailingPE`·`forwardPE`·`priceToBook`·`returnOnEquity`를 우선 수집. 값의 회계기간·조회시각·ETF 예외를 보존한다.
- **SMA·EMA:** `Ticker.history`의 가격 OHLCV를 사용해 **5·20·60·120·200일 SMA** 및 원하는 EMA/분봉 이동평균을 직접 계산한다. Yahoo 50일·200일 평균 필드는 보조 참고 값이다.
- **백테스트 주의:** 당일 조회된 기업 비율을 과거에 소급 적용하지 않고 당시 공시된 재무 데이터에만 접근하도록 설계한다. **문서화만 완료**.
- [PER·PBR·ROE 및 이동평균선 상세 명세/예제](./YFinance_Valuation_and_Moving_Averages.md).

## 최근 5·10·20거래일 최고가·최저가

- **NVDA·QLD 등 미국 주식/ETF**의 yfinance 일봉 `High`·`Low`를 사용해 최근 5·10·20개 **확정 거래일** 최고가/최저가를 직접 계산한다. **총 6개 지표**: `HIGH_5D`, `HIGH_10D`, `HIGH_20D`, `LOW_5D`, `LOW_10D`, `LOW_20D`.
- 일봉 마감 후에는 당일 완성봉을 포함하고, 장중 돌파 기준으로 사용할 때는 **직전 N개 완료 일봉**만 반영한다. 주말·휴장일을 세지 않으며 미완성 일봉과 결측을 구별한다.
- [계산식·Python 예제·가격 조정/백테스트 주의사항](./YFinance_Valuation_and_Moving_Averages.md). 운영 계산기는 미구현.

## 미국 트리플·쿼드러플 위칭

- 공식 OCC/OIC·Cboe·CME 만기 자료에서 분기 동시 만기 상품군을 확인하여 **트리플 위칭과 쿼드러플 위칭을 구분**한다. CME 개별주식 선물 재도입을 반영하고 실제 4종 동시 만기 여부를 검증한다.
- 유형별 이벤트 플래그·DTE 및 실제 거래 세션까지 남은 거래일 수를 계산한다. 자료 미확인 시 보류하며 휴장 예외와 명목 만기·정산 시각을 구별한다.
- [미국 위칭 캘린더 상세 명세](./US_Equity_Witching_Calendar.md). 문서화만 완료.

## DRAM DDR5 모듈 현물가격

- [DRAMeXchange](https://www.dramexchange.com/)의 `Module Spot Price` 표에서 **DDR5 UDIMM 16GB 4800/5600** 및 **DDR5 RDIMM 32GB 4800/5600**의 `Session Average`를 독립 지표로 수집한다. 공개 HTML 스크래핑은 자동 수집·저장·활용 권한을 확인한 뒤 활성화한다. 원본 주간 갱신 시각을 보존한다.
- [DRAMeXchange 수집 상세 명세](./DRAMeXchange_Module_Spot_Prices.md). 문서화 완료, 운영 스크래퍼 미구현.
