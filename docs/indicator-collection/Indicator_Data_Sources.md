# Auto-Axe 수집 지표별 기본 소스

| 지표 | 기본 공급원 | 갱신 / 주의 |
|---|---|---|
| 금 가격 동향 | Binance Futures `XAUUSDT` | 금 연동 영구선물 라이브 틱. 금 현물/COMEX 선물 아님 |
| 은 가격 동향 | Binance Futures `XAGUSDT` | 실시간 금속 연동 영구선물, 현물/COMEX 선물 아님 |
| 구리 가격 동향 | Binance Futures `COPPERUSDT` | 실시간 금속 연동 영구선물, 현물/COMEX 선물 아님 |
| WTI 가격 동향 | Binance Futures `CLUSDT` | 원유 연동 영구선물 라이브 틱. NYMEX 선물 아님 |
| Brent 가격 동향 | Binance Futures `BZUSDT` | 원유 연동 영구선물 라이브 틱. ICE/NYMEX 선물 아님 |
| 비트코인 | Binance Spot `BTCUSDT` | Spot 실시간 체결, USD가 아닌 USDT 호가 |
| Binance 롱숏 및 Taker 통계 | Binance Futures `/futures/data/*` | 전체 계정·상위 계정·상위 포지션·Taker 거래량 4종, 최소 5분 집계; BTC 비율은 선물, 가격은 Spot. [상세](./Binance_Metals_LongShort_20261123.md) |
| 미국 개별주식 PER·PBR·ROE | **yfinance `Ticker.info`: `trailingPE`, `forwardPE`, `priceToBook`, `returnOnEquity`** | 기업별 필드 누락 가능, 후행/예상 PER 구분; ROE 원본은 비율. ETF QLD는 기업 재무비율로 취급하지 않음. [상세](./YFinance_Valuation_and_Moving_Averages.md) |
| 이동평균선 SMA·EMA | **yfinance `Ticker.history` OHLCV 조회 → 로컬 계산** | 일봉 SMA 5·20·60·120·200 및 EMA, 분봉도 자체 계산. Yahoo `fiftyDayAverage`/`twoHundredDayAverage`는 참고. [상세](./YFinance_Valuation_and_Moving_Averages.md) |
| 최근 5·10·20거래일 최고가·최저가 | **yfinance `Ticker.history(interval='1d')`의 `High`/`Low` → `rolling().max()`/`min()` 로컬 계산** | 5·10·20개 **실제 거래세션**의 `HIGH_5D/10D/20D`, `LOW_5D/10D/20D` 6개 지표. 마감 후 당일 확정봉 포함; 장중 돌파 기준은 직전 N개 완성봉만 사용. [산출 명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 미국 주식·ETF 당일 누적 거래량 (1초 스냅샷) | **yfinance WebSocket `day_volume`**; NVDA·QLD 등 | WebSocket 신규 메시지마다 누적 거래량 갱신, **로컬 1초 스케줄러가 최신값 기록**. Yahoo 메시지의 1초 주기 도착·무지연·통합시장 거래량 보장 없음. 구현 전 실측 필요. [상세 명세](./YFinance_1s_Stock_Cumulative_Volume.md) |
| 나스닥 100 선물·연동 가격 | **MEXC Futures `NAS100_USDT` WebSocket 후보(지수 연동 영구선물)**; Binance Futures `QQQUSDT`(QQQ ETF 연동 영구선물) 참고; yfinance `NQ=F`(CME 실제 선물 지연 1분봉) 비교 | **MEXC 직접 실시간 수신 미검증**, WebSocket Protobuf 전환 2026-12-01 예정. 서로 다른 계약 가격이며 NQ=F 무지연 아님. [수집 방안](./Nasdaq100_Futures_Data_Sources.md) |
| VIX | yfinance `^VIX` | 원본 TTL 10초, 지연 가능; `UVXYUSDT` 대체 불가 |
| 미국 국채 3개월 | yfinance `^IRX` | 13-week Bill 지표, 지연 가능 |
| 미국 국채 2년 | Naver `US2YT=RR` 최우선 | [원본 페이지](https://m.stock.naver.com/marketindex/bond/US2YT=RR). 실패/실행 불가 시에만 Treasury `BC_2YEAR` 임시 일별 fallback; 원본 분리 |
| 미국 국채 5년 | yfinance `^FVX` | 지연 가능 |
| 미국 국채 10년 | yfinance `^TNX` | 지연 가능 |
| 미국 국채 30년 | yfinance `^TYX` | 지연 가능 |
| CNN 공포·탐욕 | [CNN](https://edition.cnn.com/markets/fear-and-greed) | 허가 전 자동 비활성; 허용 수동 기록 |
| 해외주식 매수·매도 결제 통계 (서학개미 수급) | [SEIBro 종목별내역(주식TOP50)](https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921) | 국가(미국 우선)·조회기간별 매수결제/매도결제/순매수결제 USD. **WebSquare 화면 스크래핑**; TOP50는 전체 해외주식 총액이 아니며 체결 아닌 결제 기준. [상세 명세](./SEIBro_Overseas_Stock_Flows.md) |
| DDR5 UDIMM 16GB 4800/5600 · RDIMM 32GB 4800/5600 | [DRAMeXchange](https://www.dramexchange.com/) `Module Spot Price`의 `Session Average` 스크래핑 (권한 확인 후) | 두 독립 모듈 현물가격 지표; 주간 갱신, 표의 Last Update 보존. [명세](./DRAMeXchange_Module_Spot_Prices.md) |
| 펜타곤 피자지수 | [PizzINT](https://www.pizzint.watch/) | 수집 권한 확인 전 수동 |
| 기업 가이던스 | SEC EDGAR/기업 IR | 원문과 추출 수치 구분 |
| 미국 경제지표 일정·실제값 | BLS·BEA·Census 공개 자료 | 발표와 수정 이력 구분 |
| 파생 만기 캘린더 | OCC·CME·Binance Options (각 상품별) | 거래소/계약마다 다름 |
| 미국 트리플·쿼드러플 위칭 | OCC/OIC·Cboe·CME (지수선물 및 개별주식선물 포함) | 실제 분기 동시 만기 상품군 3/4종 확인, 별도 이벤트·DTE·미확인 상태 저장. [상세 명세](./US_Equity_Witching_Calendar.md) |
| 중앙은행 금리 (Fed·BoJ·BoE·ECB) | 각 중앙은행 공식 발표/공개 시계열 | 실시간 시장 금리와 다름 |

**두바이유는 수집 대상에 포함하지 않는다.** 시장가격은 Binance 공개 시세, VIX·3M/5Y/10Y/30Y 수익률은 yfinance, 2Y는 네이버 증권 최우선이며 실패/실행 불가 시에만 Treasury 임시 일별 fallback이다.

[시장 데이터 소스 정책](./Market_Source_Policy_20261123.md) · [수집기](../examples/realtime_collector.py).
