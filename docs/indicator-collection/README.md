# Auto-Axe — 무료 시장 데이터 수집 설계

> 기준일: 2026-11-23. **유료 피드 제외**, 시세의 원자산·계약 종류와 시각을 명확히 구분한다. 이 저장소의 코드는 데이터 수집 PoC이며 주문 기능은 없다.

## 최신 소스 정책

- **가격·체결 데이터:** Binance 무료 **WebSocket 우선** — 금 연동 영구선물 `XAUUSDT`, WTI 연동 영구선물 `CLUSDT`, Brent 연동 영구선물 `BZUSDT`, 비트코인 현물 `BTCUSDT`. REST로도 최근 가격을 조회할 수 있다. *수신 틱이 존재할 때만* 거래소 실시간 체결이고, 거래소·계약 거래시간 밖에는 갱신되지 않는다.
- **VIX·국채 금리지표:** Binance에 동일한 원본이 없어 yfinance `^VIX`, `^IRX`, `^FVX`, `^TNX`, `^TYX` 유지 (지연 가능). **미국 2년물은 지정된 네이버 증권 페이지** [US2YT=RR](https://m.stock.naver.com/marketindex/bond/US2YT=RR)에서 값을 확인한다. 다만 `robots.txt`가 `Disallow: /`이므로 무허가 자동 수집은 비활성화; 기본은 Treasury 공식 일별 수익률로 fallback.
- **경제지표·정책·기업 가이던스·만기일:** 공식 무료 API, 보도자료, RSS/Atom, ICS 우선. 허가받은 스크래핑 또는 수동 입력.
- **수집 대상에 두바이유는 없음.**

## 미국 국채 5개 만기

| 만기 | 기본 소스 | 표기/심볼 |
|---|---|---|
| 3개월 | yfinance 지표 | `^IRX` |
| 2년 | **네이버 증권 US2YT=RR (자동화 허가 필요)** | `US2YT=RR`; 무허가 시 Treasury 일별 `BC_2YEAR` |
| 5년 | yfinance 지표 | `^FVX` |
| 10년 | yfinance 지표 | `^TNX` |
| 30년 | yfinance 지표 | `^TYX` |

Yahoo 금리지표와 미국 재무부 공식 par yield는 다른 제공 체계다. 2년물 네이버 표시값은 원본 시간·지연표시를 저장하며 국채 금리선물·레버리지 ETF로 대체하지 않는다.

## 시장 가격의 신규 기본 수집

| 관심 항목 | Binance 우선 | 정확한 자산 유형 |
|---|---|---|
| 금 | `XAUUSDT` | USDT 표시 **금 연동 무기한 선물**, 금 현물 XAU/USD·COMEX `GC=F`와 다름 |
| WTI | `CLUSDT` | Binance 원유 연동 무기한 선물, NYMEX `CL=F`와 다름 |
| Brent | `BZUSDT` | Binance 원유 연동 무기한 선물, NYMEX `BZ=F`와 다름 |
| 비트코인 | `BTCUSDT` | Binance Spot BTC/USDT, Yahoo BTC-USD와 호가통화 다름 |
| VIX | yfinance `^VIX` | Binance `UVXYUSDT`는 **다른 파생상품** |
| 국채 3M/5Y/10Y/30Y | yfinance 금리지표 | Binance `TMFUSDT`·`TBTUSDT`는 별개 장기채 레버리지·인버스 ETF 연동 계약 |

금의 참고 **현물 추정가격**은 별도 `gold-spot-reference` 명령으로 Gold API를 사용할 수 있다. 기본 거래소 라이브 가격과 혼합하지 않는다.

## 빠른 실행

```bash
python -m pip install -r docs/examples/requirements.txt

# Binance 라이브 트레이드 스트림: 금/WTI/Brent 영구선물 + BTC Spot
python docs/examples/realtime_collector.py binance-live

# Binance 연동 선물 최근 가격 REST 1회
python docs/examples/realtime_collector.py binance-futures

# VIX와 국채 3M/5Y/10Y/30Y: yfinance 지연 가능
python docs/examples/realtime_collector.py yf-market

# 2년물: 네이버 사이트의 수집 승인이 없는 동안 공식 Treasury 일별 값
python docs/examples/realtime_collector.py treasury-five

# 네이버: 승인을 받은 경우에만 AUTO_AXE_NAVER_SCRAPE_AUTHORIZED=1 설정
python docs/examples/realtime_collector.py naver-2y
```

## 문서

- [실시간 공급원 전환 상세 명세](./Market_Source_Policy_20261123.md) · [Binance API 직접 검증](./Binance_API_Coverage.md)
- [실행 가이드](./Realtime_Quickstart.md) · [전체 무료 데이터 카탈로그](./Free_Data_Collection.md) · [수집기 아키텍처](./Collector_Design.md)
- [yfinance 지원 검증](./YFinance_Data_Validation.md) · [과거 yfinance 우선 설계(변경 이력)](./YFinance_First_Collection.md)
- [수동 기록 정책](./Manual_Collection.md) · [실행 코드](../examples/realtime_collector.py) · [스크래핑 권한 검증 예제](../examples/naver_bond_source_probe.py)

> Binance 무료 공개 시장데이터는 거래소의 공개 시세일 뿐, 다른 거래소의 무지연 가격 또는 현물 지표와 동일하다는 의미는 아니다. 해당 상품의 제공 지역 및 Binance 이용조건을 확인한다.

## 구리·은 및 Binance 롱숏 비율 추가 (2026-11-23)

- **구리:** Binance Futures `COPPERUSDT`, 내부 `COPPER_BINANCE_PERP`; **은:** `XAGUSDT`, 내부 `SILVER_BINANCE_PERP`. 두 종목 모두 실측 `TRADING / TRADIFI_PERPETUAL`, REST 1분봉 지원. 기존 Binance Futures `@aggTrade` 실시간 스트림의 구독 목록에 추가했다. USDT 표시 영구선물은 원자재 현물 또는 거래소 만기선물과 다르다.
- **공식 롱숏 비율 4종:** 전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율. Binance `/futures/data/*` 무료 공개 REST의 **최소 5분 집계**로 수집한다. 실시간 WS 틱이 아니며, Taker 매수·매도 비율은 포지션 롱숏 비율과 다르다.
- `python docs/examples/realtime_collector.py binance-live`: BTC Spot + 금·은·구리·WTI·Brent 5개 영구선물.
- `python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300`: 6개 Binance 선물 심볼의 롱숏·Taker 통계 5분 간격 조회.
- [상세 응답 검증과 API 구분](./Binance_Metals_LongShort_20261123.md) · [Python 수집기](../examples/realtime_collector.py).
