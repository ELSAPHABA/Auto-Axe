# 실시간·준실시간 시장 지표: yfinance 우선

> 무료 수집 정책. yfinance가 조회 가능한 가격·금리지표는 **1분봉/일봉 폴링**으로 수집하되 **무지연 real-time이 보장되지 않는다**. 공식 원본의 의미가 다르면 별도 시계열로 유지한다.

## yfinance 기본 대상

| 대상 | 심볼 | 유형·제약 |
|---|---|---|
| VIX | `^VIX` | 지수 (원시 Cboe 피드와 시차 미검증) |
| 미국 3개월물 | `^IRX` | 13주 Treasury Bill 지표 |
| 미국 **2년물** | **yfinance 정확한 현물 수익률 심볼 미확인** | US Treasury `BC_2YEAR` **일별** 공식 XML |
| 미국 5년물 | `^FVX` | 국채 금리지표 |
| 미국 10년물 | `^TNX` | 국채 금리지표 |
| 미국 30년물 | `^TYX` | 국채 금리지표 |
| WTI 선물 | `CL=F` | NYMEX 원유 선물, Yahoo 지연표시 |
| Brent 선물 | `BZ=F` | NYMEX Brent Financial 선물, Yahoo 지연표시 |
| 금 선물 | `GC=F` | COMEX 선물 (금 현물 아님) |
| BTC/USD | `BTC-USD` | Yahoo 집계시세, 무료 거래소 공개 WS는 별도 |

**두바이유 현물 일별 시세는 동일한 yfinance 심볼이 확인되지 않아** World Bank/IMF 무료 월평균과 수동 입력 경로로 남긴다.

## 무료 공식 데이터로 교차 검증하는 값

- U.S. Treasury [par-yield XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) 3M/2Y/5Y/10Y/30Y는 **일별**; Yahoo Cboe 지표와 수치가 같다고 가정하지 않는다.
- EIA `PET.RWTC.D`·`PET.RBRTE.D`는 **일별 현물**, `CL=F`·`BZ=F`는 **선물**.
- Cboe `VIX_History.csv`는 **일별**, yfinance `^VIX` 분봉과 비교·검증.
- Gold API `/price/XAU`는 금 현물 추정, `GC=F`는 금 선물.
- BTC Coinbase/Binance 공개 WebSocket은 개별 거래소 체결틱이며 `BTC-USD` 시장 요약시세와 별개.

**지원 한계:** yfinance 라이브러리에 `WebSocket`과 `AsyncWebSocket`이 있어도 모든 상기 심볼의 구독 이벤트·무지연 시세 전달이 입증된 것은 아니다. 운영 기본은 `Ticker.history`로 최신 봉 조회. 지연시각·출처·데이터 라이선스 확인 필요. [yfinance 참고문서](https://ranaroussi.github.io/yfinance/reference/index.html).

CNN 출처는 [edition.cnn.com](https://edition.cnn.com/markets/fear-and-greed), 피자지수는 [PizzINT](https://www.pizzint.watch/). 사이트 접근이 가능해도 자동 스크래핑 허가가 없으면 수동으로 남긴다.

## 실행

```bash
python -m pip install -r docs/examples/requirements.txt
python docs/examples/realtime_collector.py yf-market --period 1d --bar-interval 1m
python docs/examples/realtime_collector.py treasury-five
```

자세한 지표 정의: [YFinance_First_Collection.md](./YFinance_First_Collection.md). 추가 무료 데이터: [Free_Data_Collection.md](./Free_Data_Collection.md).
