# yfinance 기업 가치·수익성 지표 및 이동평균선 수집·산출 명세

> Auto-Axe 무료 지표 수집 정책 · 2026-11-24 · 상태: **문서화 완료 / 실제 수집기 구현 및 NVDA·QLD 응답 검증 미완료**

## 1. 기본 원칙

- 미국 **개별 주식(NVDA 등)의 PER·PBR·ROE는 yfinance `Ticker.info`에서 우선 조회**한다. 세부 값은 제공자의 산식·갱신 주기·대상 종목에 따라 없거나 늦을 수 있다.
- **최근 5·10·20거래일 최저가·최고가는 yfinance 일봉의 `Low`·`High`를 로컬 rolling min/max로 직접 계산**한다. 주말·휴장일을 포함한 달력상 5/10/20일이 아니라 해당 종목의 **실제 거래 세션 5/10/20개**를 사용한다.
- **이동평균선(SMA·EMA)은 yfinance `Ticker.history`의 OHLCV에서 직접 계산**한다. Yahoo가 제공하는 50일/200일 평균 필드는 보조 검증 정보일 뿐 모든 기간 이동평균을 직접 반환하는 범용 API는 아니다.
- **ETF(예: QLD)를 일반 사업회사와 동일한 PER·PBR·ROE로 취급하지 않는다.** ETF 운용사·기초 보유기업의 집계 지표와 펀드 자체 재무지표는 정의가 다르며, 기본 결측 처리한다.
- 기업 가치/수익성 지표, 기술적 지표, 실시간 시세/거래량은 **다른 갱신 주기·원본 시각**을 갖는 시계열로 분리한다.

## 2. 지원 현황 및 내부 표준

| 지표 | yfinance 원본 필드 | 기본 처리 | 해석/비고 |
|---|---|---|---|
| PER (후행, TTM) | `trailingPE` | `Ticker.info` 조회 | 주가 ÷ 최근 12개월 EPS. 0·음수 EPS인 기업은 값이 없거나 해석에 주의 |
| PER (예상) | `forwardPE` | `Ticker.info` 조회 | 예상 EPS에 기반. 애널리스트 컨센서스 시점·정의가 바뀔 수 있음 |
| PBR | `priceToBook` | `Ticker.info` 조회 | 주가 ÷ BPS. 자기자본이 음수이거나 장부가치가 특이하면 해석에 주의 |
| ROE | `returnOnEquity` | `Ticker.info` 조회 | 비율 원본. `0.35` → `35%`; 1을 넘는 ROE도 가능 |
| 50일 SMA (Yahoo 참고) | `fiftyDayAverage` | **보조 대조** | 제공자의 가격 조정/윈도우 정책과 직접 계산 결과가 다를 수 있음 |
| 200일 SMA (Yahoo 참고) | `twoHundredDayAverage` | **보조 대조** | 동일 |
| 5·20·60·120·200일 SMA | `Ticker.history(...).Close` | **직접 계산** | 선택한 기간의 **확정 거래일 종가** 이동평균 |
| 최근 5·10·20거래일 최저가 | `Ticker.history(...).Low` | **rolling 최솟값 직접 계산** | 각 최근 N개 확정 일봉의 일중 최저가. `LOW_5D`·`LOW_10D`·`LOW_20D` |
| 최근 5·10·20거래일 최고가 | `Ticker.history(...).High` | **rolling 최댓값 직접 계산** | 각 최근 N개 확정 일봉의 일중 최고가. `HIGH_5D`·`HIGH_10D`·`HIGH_20D` |
| EMA(예: 12·26일), 분봉 SMA·EMA | `Ticker.history(...)` | **직접 계산** | 봉 주기·조정 가격·초기화 `adjust` 및 `min_periods` 명시 |

### 관련 계산식

```text
PER_TTM = price_at_t / eps_ttm_at_t
PER_FORWARD = price_at_t / forecast_eps_at_t
PBR = price_at_t / book_value_per_share_at_t
ROE = net_income_ttm / ((beginning_equity + ending_equity) / 2)
SMA_N(t) = mean(close[t-N+1:t])       # N개 확정봉
EMA_N(t) = EMA_N(t-1) * 2/(N+1) + close[t] * (1-2/(N+1))
LOW_ND(t) = min(low[t-N+1], ..., low[t])    # N=5,10,20; 확정 거래일 일봉
HIGH_ND(t) = max(high[t-N+1], ..., high[t]) # N=5,10,20; 확정 거래일 일봉
LIVE_LOW_ND(t) = min(low[t-N], ..., low[t-1])   # 당일 장중: 직전 N개 완성봉
LIVE_HIGH_ND(t) = max(high[t-N], ..., high[t-1]) # 당일 장중: 직전 N개 완성봉
```

- PER/PBR은 기준 주가와 EPS/BPS의 통화·주식분할 조정·기준 시점을 정합시켜야 한다. `Ticker.info`의 공급자 산식을 임의로 재생산한 값과 비교할 때는 조건을 기록한다.
- ROE를 직접 산출할 경우 분자 순이익 기간과 분모의 자기자본 평균기간을 맞추고, 회계상 자기자본 정의(지배지분 등)·회계기준을 기록한다. 음수·0에 가까운 자본으로 비율이 왜곡될 수 있다.
- **단순 이동평균은 N개 관측치가 모이기 전에는 `NaN`**으로 두어 워밍업 부족을 명확히 표시한다.
- EMA는 seed 및 `pandas.ewm(adjust=False, min_periods=N)` 정책을 저장해 재현 가능하게 한다.

## 3. Python 예시

다음 코드는 **NVDA**를 예시로, 원본 재무비율 스냅샷과 **배당·분할 조정 일봉**의 SMA·EMA를 별도로 계산한다. 실제 수집 테스트가 완료됐다는 뜻은 아니다.

```python
import yfinance as yf

symbol = "NVDA"
ticker = yf.Ticker(symbol)
info = ticker.info

fundamentals = {
    "symbol": symbol,
    "per_ttm": info.get("trailingPE"),
    "per_forward": info.get("forwardPE"),
    "pbr": info.get("priceToBook"),
    "roe_ratio": info.get("returnOnEquity"),  # 0.35 = 35%, 원본 ratio 보존
    "sma_50_yahoo_reference": info.get("fiftyDayAverage"),
    "sma_200_yahoo_reference": info.get("twoHundredDayAverage"),
}
print(fundamentals)

# 200개 이상의 거래일 확보; 분할/배당 조정종가를 일관되게 사용
bars = ticker.history(period="2y", interval="1d", auto_adjust=True)
close = bars["Close"]

for days in (5, 20, 60, 120, 200):
    bars[f"SMA_{days}D"] = close.rolling(
        window=days, min_periods=days
    ).mean()

for days in (5, 10, 20):
    # 확정된 일봉만 입력해야 함. 아래의 현재 진행 중인 당일 봉 제외 정책 참조.
    bars[f"LOW_{days}D"] = bars["Low"].rolling(
        window=days, min_periods=days
    ).min()
    bars[f"HIGH_{days}D"] = bars["High"].rolling(
        window=days, min_periods=days
    ).max()

for days in (12, 26):
    bars[f"EMA_{days}D"] = close.ewm(
        span=days, adjust=False, min_periods=days
    ).mean()

# 미완성 현재 일봉은 운영 환경에서 확정 여부를 판단한 뒤 사용
print(bars.filter(regex="^(SMA_|EMA_|LOW_|HIGH_)").tail())
```

**ETF 주의:** `yf.Ticker("QLD").info`에 PER·PBR·ROE 필드가 없으면 `null`로 기록한다. 보유 종목의 가중평균 PER/PBR/ROE를 요구할 경우 **ETF 구성종목·가중치의 유효 시각**을 따로 수집해 **새 지표명**으로 계산해야 한다. 레버리지 ETF의 일별 목표 배율과 구성종목 가치평가를 동일시하지 않는다.

### 5·10·20거래일 최고가·최저가 지표 정의

- **대상:** NVDA·QLD 등 미국 주식·ETF의 일봉 `High` / `Low`. `Close`의 최고/최저가 아니라 **각 거래일의 장중 고가와 장중 저가** 기준이다. 종가 기준 최고·최저가를 추가한다면 `CLOSE_HIGH_ND` / `CLOSE_LOW_ND` 등 **별도 이름**으로 관리한다.
- **범위:** `LOW_5D`, `LOW_10D`, `LOW_20D`와 `HIGH_5D`, `HIGH_10D`, `HIGH_20D`로 **총 6개 파생 지표**. 예컨대 `HIGH_10D(t)`는 **당일 t를 포함한 최근 확정 일봉 10개** 중 가장 높은 `High`다.
- **'영업일' 정의:** 주식시장 거래소의 **실제 정상 거래 세션 중 유효 일봉이 존재한 날**만 1개로 센다. 미국 휴장일·주말은 세지 않고, 반일장도 실제 거래가 있는 1개 세션으로 센다. 결측 일봉을 0으로 채우거나 단순 평일(`BusinessDay`)로 세지 않는다.
- **정규장/시간외:** 기준 일봉의 장중 `High/Low`를 사용하되, yfinance의 세션별 포함 범위는 실측 검증한다. 시간외까지 포함하는 별도 실시간 고저가와 혼합하지 않는다.
- **일봉 확정 후:** 그날의 완성된 `High`·`Low`를 반영해 최근 N거래일 범위를 재계산한다. **현재 진행 중인 봉(특히 미국 장중 마지막 일봉)**을 포함해 일봉 마감 최고·최저가로 확정 저장하지 않는다.
- **장중 돌파 판단:** 장중 현재가와 비교할 상단/하단 기준은 **직전 N개 '완성' 일봉**의 `max(High)` / `min(Low)`. 오늘의 진행 중 `High/Low`를 기준값에 포함하면 이미 갱신된 가격이 기준을 끌어올려 돌파 판단이 왜곡된다.
- **가격 조정 기준:** `auto_adjust=True`이면 배당·분할 조정된 `High/Low`가 사용될 수 있다. 실제 과거 장중 가격 기준을 원하면 `auto_adjust=False`를 선택하고 조정·분할 정책을 일관되게 유지한다. 비교 가격도 같은 가격 기준이어야 한다.
- **워밍업:** 최근 N개 유효 거래일 일봉이 확보되지 않으면 `NaN`/결측 처리한다. 백테스트에서는 당시 시점에 **이미 확정된 일봉**만 사용한다.

별도 확정 일봉 데이터 프레임 `closed_bars`를 확보했다는 전제의 Python 구현 예시:

```python
# closed_bars: 'High', 'Low'를 포함하고 거래 종료가 확인된 일봉만 들어 있음.
# 예: bars에서 오늘 진행 중인 마지막 일봉을 사전에 제외한 DataFrame.
closed_bars = bars.loc[bars["High"].notna() & bars["Low"].notna()].copy()
# 실제 운영에서는 이 필터만으로 '봉 확정'을 판정할 수 없음:
# 거래소 세션/당일 마감 여부를 확인해 진행 중인 일봉을 먼저 제외해야 한다.
for n in (5, 10, 20):
    closed_bars[f"LOW_{n}D"] = closed_bars["Low"].rolling(
        window=n, min_periods=n
    ).min()
    closed_bars[f"HIGH_{n}D"] = closed_bars["High"].rolling(
        window=n, min_periods=n
    ).max()

    # 장중 신호용: 직전 N개의 완성 일봉만 기준으로 비교.
    # 최신 완성 일봉 N개를 사용하고, 진행 중인 당일 일봉은 포함하지 않는다.
    if len(closed_bars) >= n:
        live_low = closed_bars["Low"].iloc[-n:].min()
        live_high = closed_bars["High"].iloc[-n:].max()
        print(n, live_low, live_high)
```

**개발 주의:** 이 예시의 `closed_bars`는 **완성 일봉만 제공하는 상위 수집 파이프라인**이 준비되었다는 전제다. 위 `notna()` 필터는 일봉의 확정 여부를 판정하지 않으므로, 장중에 `bars`를 그대로 넣어 오늘의 진행 중인 봉을 포함시키지 말 것. 마감 후 확정 자료와 장중 참고용 시계열을 분리한다.

## 4. Auto-Axe 수집·계산 주기

| 지표 | 권장 운영 주기 | 저장 시 유의 |
|---|---|---|
| `trailingPE`·`forwardPE`·`priceToBook` | **일 1회** 기본 스냅샷 | 주가 변화로 장중 지표가 움직일 수 있음. 장중 사용 시 당일 유효 EPS/BPS/예상치를 별도 저장 후 계산 |
| `returnOnEquity` | **실적 공시 뒤 재확인**, 운영상 일별 결측·변경 감지 가능 | 회계 분기 기준·공시 후 유효시간, 발표 지연 기록 |
| 일봉 최근 5·10·20거래일 최고·최저가 | **일봉 확정 후 1회** | 당일 포함 확정 N봉 범위 고·저가 6개 계산. 장중은 **직전 N개 확정봉** 기준값을 별도 사용 |
| 일봉 SMA/EMA | **일봉 확정 후 1회** | 교정·배당/분할에 따른 과거 조정값 변경 가능 |
| 1분·5분봉 SMA/EMA | 해당 **봉 확정 시** | 미완성 봉과 확정 봉 분리; 서버 측 OHLCV 조회 범위 제한 확인 |
| 실시간 가격 반영 동적 SMA | 가격 WebSocket이 실제 도착할 때 계산 | 마지막 **완료 봉 기준 SMA**와 진행 중 갱신 SMA를 서로 다른 지표로 저장 |

- **미국 주식 시세, 실적 발표, 회계 결산은 서로 다른 시간축**이다. `fetched_at_utc`, `published_at_utc`(알 수 있는 경우), `financial_period_end`, `price_timestamp`, `calculated_at_utc`, `adjusted_price`를 별도 보관한다.
- `Ticker.info`는 **현재 조회 시점의 요약 정보**로, 과거 날짜별 PER/PBR/ROE 스냅샷 API가 아니다. **백테스트에서 오늘의 지표를 과거에 소급 적용하지 않는다**(look-ahead bias). 실제 과거 공시·재무제표의 공개 시각과 해당 시점 주가로 PIT(Point-in-time) 재구성한다.
- 단순 `Ticker.history`의 과거 배당·분할 조정 가격도 당시 시장이 알 수 없었던 향후 기업행동을 소급 반영할 수 있다. 백테스트 목적에 따라 당시 유효한 조정값/기업행동 기록을 선택하고 보존한다.
- ETF·선물·지수·암호화폐는 기업 재무 PER·PBR·ROE를 기본으로 강제하지 않는다. 해당 종목군의 기술지표는 각각의 별도 기초 가격 시리즈로 계산한다.

## 5. 저장 스키마 제안

```text
fundamental_snapshots:
  symbol, provider, metric, value, unit,
  fetched_at_utc, financial_period_end?, published_at_utc?,
  valuation_price_at?, earnings_basis?, estimated_or_reported,
  asof_validation_status, asset_type

technical_indicators:
  symbol, provider, interval, indicator, window, value,
  close_basis (adjusted/unadjusted), bar_closed_at_utc,
  calculated_at_utc, is_final_bar, warmup_complete, source_url
  # 최근 최고·최저가의 경우: price_field=High|Low,
  # window_sessions=5|10|20, includes_current_closed_bar=true|false,
  # session_scope=regular, adjustment_policy, sample_has_n_complete_bars
```

**결측은 0으로 채우지 않는다.** 비율의 단위(`roe_ratio`와 `roe_percent`)를 섞지 않으며, 계산식·윈도우·파라미터 버전을 저장한다.

## 6. 출처·구현 상태

- [yfinance Ticker.info 공식 레퍼런스](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.info.html)
- [yfinance Ticker.history 공식 레퍼런스](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html)
- [yfinance Ticker API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html) · [펀드·ETF 전용 데이터](https://ranaroussi.github.io/yfinance/reference/yfinance.ticker_tickers.html)
- [pandas rolling mean 공식 문서](https://pandas.pydata.org/docs/reference/api/pandas.core.window.rolling.Rolling.mean.html) · [pandas EWM 공식 문서](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html)
- [관련 지표 목록](./Indicator_Data_Sources.md) · [실시간 가격·거래량](./Real_Time_Data_Sources.md) · [전체 수집 정책](./Market_Source_Policy_20261123.md)

현재 **문서 등록만 수행**. `docs/examples/realtime_collector.py`에는 신규 `fundamentals`/MA 명령을 추가하지 않는다. 운영 구현 전에 Yahoo 현재 필드가 해당 종목에서 실제 반환되는지 테스트하고 시계열 적재·재배포 사용권을 확인한다.
