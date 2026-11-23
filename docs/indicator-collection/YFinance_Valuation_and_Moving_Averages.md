# yfinance 기업 가치·수익성 지표 및 이동평균선 수집·산출 명세

> Auto-Axe 무료 지표 수집 정책 · 2026-11-24 · 상태: **문서화 완료 / 실제 수집기 구현 및 NVDA·QLD 응답 검증 미완료**

## 1. 기본 원칙

- 미국 **개별 주식(NVDA 등)의 PER·PBR·ROE는 yfinance `Ticker.info`에서 우선 조회**한다. 세부 값은 제공자의 산식·갱신 주기·대상 종목에 따라 없거나 늦을 수 있다.
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
| EMA(예: 12·26일), 분봉 SMA·EMA | `Ticker.history(...)` | **직접 계산** | 봉 주기·조정 가격·초기화 `adjust` 및 `min_periods` 명시 |

### 관련 계산식

```text
PER_TTM = price_at_t / eps_ttm_at_t
PER_FORWARD = price_at_t / forecast_eps_at_t
PBR = price_at_t / book_value_per_share_at_t
ROE = net_income_ttm / ((beginning_equity + ending_equity) / 2)
SMA_N(t) = mean(close[t-N+1:t])       # N개 확정봉
EMA_N(t) = EMA_N(t-1) * 2/(N+1) + close[t] * (1-2/(N+1))
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

for days in (12, 26):
    bars[f"EMA_{days}D"] = close.ewm(
        span=days, adjust=False, min_periods=days
    ).mean()

# 미완성 현재 일봉은 운영 환경에서 확정 여부를 판단한 뒤 사용
print(bars.filter(regex="^(SMA_|EMA_)").tail())
```

**ETF 주의:** `yf.Ticker("QLD").info`에 PER·PBR·ROE 필드가 없으면 `null`로 기록한다. 보유 종목의 가중평균 PER/PBR/ROE를 요구할 경우 **ETF 구성종목·가중치의 유효 시각**을 따로 수집해 **새 지표명**으로 계산해야 한다. 레버리지 ETF의 일별 목표 배율과 구성종목 가치평가를 동일시하지 않는다.

## 4. Auto-Axe 수집·계산 주기

| 지표 | 권장 운영 주기 | 저장 시 유의 |
|---|---|---|
| `trailingPE`·`forwardPE`·`priceToBook` | **일 1회** 기본 스냅샷 | 주가 변화로 장중 지표가 움직일 수 있음. 장중 사용 시 당일 유효 EPS/BPS/예상치를 별도 저장 후 계산 |
| `returnOnEquity` | **실적 공시 뒤 재확인**, 운영상 일별 결측·변경 감지 가능 | 회계 분기 기준·공시 후 유효시간, 발표 지연 기록 |
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
```

**결측은 0으로 채우지 않는다.** 비율의 단위(`roe_ratio`와 `roe_percent`)를 섞지 않으며, 계산식·윈도우·파라미터 버전을 저장한다.

## 6. 출처·구현 상태

- [yfinance Ticker.info 공식 레퍼런스](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.info.html)
- [yfinance Ticker.history 공식 레퍼런스](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html)
- [yfinance Ticker API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html) · [펀드·ETF 전용 데이터](https://ranaroussi.github.io/yfinance/reference/yfinance.ticker_tickers.html)
- [pandas rolling mean 공식 문서](https://pandas.pydata.org/docs/reference/api/pandas.core.window.rolling.Rolling.mean.html) · [pandas EWM 공식 문서](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html)
- [관련 지표 목록](./Indicator_Data_Sources.md) · [실시간 가격·거래량](./Real_Time_Data_Sources.md) · [전체 수집 정책](./Market_Source_Policy_20261123.md)

현재 **문서 등록만 수행**. `docs/examples/realtime_collector.py`에는 신규 `fundamentals`/MA 명령을 추가하지 않는다. 운영 구현 전에 Yahoo 현재 필드가 해당 종목에서 실제 반환되는지 테스트하고 시계열 적재·재배포 사용권을 확인한다.
