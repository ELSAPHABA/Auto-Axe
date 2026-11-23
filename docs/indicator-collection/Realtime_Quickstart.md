# Auto-Axe 무료 데이터 수집 실행 가이드 (2026-11-23)

> 2026-11-22 · **구독비 0원만 대상**. 모든 샘플은 연구/개발 참고용으로, 공급자별 허용 범위와 가용성을 유지하고 실제 실시간성·지연을 별도 확인한다. **무료 REST 조회를 초 단위로 반복해도 일별 데이터가 실시간으로 바뀌지 않는다.**

## 0. 기본 수집 — Binance 실시간 + 국채 5만기

```bash
python -m pip install -r docs/examples/requirements.txt

# Binance 현물 BTC/USDT 및 금·WTI·Brent 연동 영구선물 체결 실시간 WS
python docs/examples/realtime_collector.py binance-live

# Binance 영구선물 최신 가격 REST 1회
python docs/examples/realtime_collector.py binance-futures

# Binance가 원본 지표를 지원하지 않는 경우: VIX, 국채 3M/5Y/10Y/30Y
python docs/examples/realtime_collector.py yf-market --symbols VIX UST_3M UST_5Y UST_10Y UST_30Y --period 1d --bar-interval 1m

# 국채 2Y 지정 출처 네이버 US2YT=RR (robots 전체 차단; 승인 없는 한 실행 불가)
python docs/examples/realtime_collector.py naver-2y

# 승인 전 기본 fallback: 미국 재무부 공식 국채 2Y 포함 5개 만기 일별
python docs/examples/realtime_collector.py treasury-five

# 금 현물 추정가격은 선택적 참고 시리즈 (기본 금 영구선물과 별개)
python docs/examples/realtime_collector.py gold-spot-reference
```

네이버 모바일 증권의 `US2YT=RR` 화면은 `closePrice`·`localTradedAt` 필드를 제공하지만, `robots.txt`가 `Disallow: /`이므로 무허가 자동 수집을 활성화할 수 없다. 사이트 운영자로부터 별도 허가를 확보한 경우에만 `AUTO_AXE_NAVER_SCRAPE_AUTHORIZED=1` 설정 후 `naver-2y` 명령을 사용한다. 이 조건을 충족하기 전에는 공식 Treasury 일별값으로 표기한다.

**주의:** Binance `XAUUSDT`, `CLUSDT`, `BZUSDT`는 **원자재 연동 영구선물**, `BTCUSDT`는 **USDT 호가 현물**이다. 이들은 Yahoo `GC=F`·`CL=F`·`BZ=F`, 금 현물 또는 BTC/USD와 동일하지 않다. [최신 소스 정책](./Market_Source_Policy_20261123.md).

## 1. 설치

Python 3.11 이상:

```powershell
git clone https://github.com/ELSAPHABA/Auto-Axe.git
cd Auto-Axe
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r docs/examples/requirements.txt
Copy-Item docs/examples/.env.example .env
```

Linux/macOS에서는 `source .venv/bin/activate` 후 `cp docs/examples/.env.example .env`. .env의 SEC 연락처/선택 키는 본인의 것으로 바꾼다. Git에 비밀키를 업로드하지 않는다.

## 2. 거래소 체결 보조 연결 (기본 Binance 실시간 스트림은 위 0절)

Coinbase BTC-USD 체결 기반 ticker:

```bash
python docs/examples/realtime_collector.py coinbase
```

Binance BTCUSDT 체결 및 **마감된 1분봉**:

```bash
python docs/examples/realtime_collector.py binance
```

각 명령은 콘솔에 JSON Lines로 출력한다. 연결이 끊어지면 재접속을 시도하지만 생산환경에는 누락 구간 REST 백필과 이벤트 sequence 검증이 추가로 필요하다. **USD와 USDT는 다른 호가통화**다. [Coinbase WS](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview), [Binance WS](https://developers.binance.com/en/docs/products/spot/web-socket-streams).

## 3. 보조 금 현물 참고가격 (기본 금 가격은 Binance 영구선물)

```bash
curl https://api.gold-api.com/price/XAU
python docs/examples/realtime_collector.py gold-spot-reference --interval 60
```

공급자 `updatedAt` 기준으로 중복제거. 실제 거래소 체결 틱·LBMA Gold Price가 아니다. [Gold API](https://gold-api.com/docs).

## 4. 기업 실적 가이던스: SEC 무료 신규 공시 감시

실제 연락처 포함 UA를 `.env`에 설정:

```dotenv
AUTO_AXE_USER_AGENT=AutoAxe Research your-email@example.com
```

```bash
python docs/examples/realtime_collector.py sec-8k --interval 90
```

공식 `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=exclude&count=100&output=atom`에서 새로운 제출을 감지한다. 8-K 원문/첨부 `Exhibit 99.1`과 기업 공식 IR RSS/보도자료에서 `outlook`, `guidance`, `FY/Q`, `EPS`, `revenue` 수치를 추출해야 **실제 가이던스**가 된다. **현재 스크립트는 신규 8-K 탐지만 구현**했으므로 가이던스 수치가 자동 추출되는 것처럼 사용하지 않는다.

무료 공식 기업 IR RSS 예시:

- NVIDIA Press Releases: `https://nvidianews.nvidia.com/cats/press_release.xml`
- NVIDIA IR Events: `https://investor.nvidia.com/rss/event.aspx`
- NVIDIA SEC Filing: `https://investor.nvidia.com/rss/SECFiling.aspx?Exchange=CIK&Symbol=0001045810`
- 미국 연준 정책 RSS: `https://www.federalreserve.gov/feeds/press_monetary.xml`
- 일본은행 What's New: `https://www.boj.or.jp/en/rss/whatsnew.xml`
- ECB 보도자료: `https://www.ecb.europa.eu/rss/press.html`

위 공식 RSS는 다음 명령으로 직접 감시할 수 있다.

```bash
python docs/examples/realtime_collector.py rss --feed fed --interval 300
python docs/examples/realtime_collector.py rss --feed boj --interval 300
python docs/examples/realtime_collector.py rss --feed ecb --interval 300
python docs/examples/realtime_collector.py rss --feed nvidia-pr --interval 600
```

각 피드는 RSS 제공 사이트 공식 링크에서 확인된 예이다. [RSS 허용 수집 예제](#8-api가-없을-때-허용된-스크래핑)를 이용해 신규 글의 `guid`·`url`·게시시각을 보관한다. PDF/본문 가이던스 수치의 문맥 검증은 별도 작업이다.

SEC는 식별 가능한 `User-Agent`, 전체 IP 기준 초당 10요청 이하 및 공정접근 정책 준수. [SEC 공식 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

## 5. 미국 경제지표 발표 일정 및 실제값

공식 BLS 발표 일정 ICS:

```bash
python docs/examples/realtime_collector.py bls-calendar --interval 3600
```

실제 BLS 공표된 지표(무료 API; 무키 일일 쿼터 제한):

```bash
python docs/examples/realtime_collector.py bls-actual
```

발표 자료 `https://www.bls.gov/news.release/cpi.htm`, `https://www.bls.gov/news.release/empsit.htm`. [BLS API FAQ](https://www.bls.gov/developers/api_faqs.htm): 미등록 일 25 호출, 등록 키 일 500 호출 등의 한도를 확인한다. **발표 직후 API 반영이 지연될 수 있어** 공식 보도자료 HTML을 허용 범위에서 읽고, API로 교차검증한다.

무료 BEA GDP/PCE API: [BEA API 문서](https://apps.bea.gov/API/docs/index.htm), `GET https://apps.bea.gov/api/data/?UserID=YOUR_KEY&method=GetData&datasetname=NIPA&TableName=T10101&Frequency=Q&Year=2026&ResultFormat=JSON` (예제 테이블/파라미터는 실제 응답 확인). Census 경제지표 [공식 페이지](https://www.census.gov/economic-indicators/).

발표 일정은 `scheduled_at`, 실제 발표는 `released_at`, API 관측은 `received_at`으로 구분. 미국 `America/New_York` DST 변환 필요.

## 6. 공식 일별 데이터 — Binance 상품과 구별되는 원본가격/국채 2Y fallback

무료 EIA API 키를 받아 `.env`에 추가:

```bash
python docs/examples/realtime_collector.py eia --series PET.RWTC.D
python docs/examples/realtime_collector.py eia --series PET.RBRTE.D
```

yfinance VIX `^VIX`의 공식 과거 검증용 Cboe **EOD**:

```bash
python docs/examples/realtime_collector.py vix-eod
```

미국 재무부 무료 국채 금리 **일별** XML 원본:

```bash
curl "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month=202611"
```

FRED 이용약관 및 원 소스의 권리를 확인한 뒤 허용되는 방식으로 FRED 무료 키를 사용할 경우 참고조회:

```bash
python docs/examples/realtime_collector.py fred --series DGS10
python docs/examples/realtime_collector.py fred --series DFEDTARU
```


## 7. 중앙은행 결정 및 파생상품 만기

- Fed 결정: `https://www.federalreserve.gov/feeds/press_monetary.xml` + [FOMC 일정](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).
- BOJ 발표: `https://www.boj.or.jp/en/rss/whatsnew.xml` + [BOJ 무료 API](https://www.stat-search.boj.or.jp/info/api_manual_en.pdf). **실효 콜금리와 정책 목표금리 분리**.
- BoE 일별 Bank Rate: `https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?CSVF=TN&Datefrom=01%2FJan%2F1975&Dateto=now&SeriesCodes=IUDBEDR&UsingCodes=Y&html.x=yes`; MPC 결정 성명 HTML에서 발표일과 발효일 추출.
- ECB 무료 DFR SDMX: `https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?lastNObservations=5&format=csvdata`; [공식 ECB 데이터 API](https://data.ecb.europa.eu/help/api/data).
- 파생 만기: [OCC/OIC](https://www.optionseducation.org/referencelibrary/expiration-calendar), [CME 만기](https://www.cmegroup.com/tools-information/calendars/expiration-calendar.html) 공식 무료 공개 달력에서 날짜/최종거래/처리/결제를 별도 저장. 2026-06-19 Juneteenth의 옵션 처리일은 2026-06-18인 사례가 있다 ([OCC 공식 메모](https://infomemo.theocc.com/infomemos?number=59161)).

## 8. API가 없을 때 허용된 스크래핑

**RSS, ICS, 공개 CSV 등 기계 판독 원본을 HTML보다 먼저 사용한다.** 사이트의 약관·robots·저작권·자동화 허용 여부를 확인한 공개 공시/정부 페이지에서만 requests+BeautifulSoup을 쓴다. 구조를 검사하지 않은 CSS 셀렉터를 확정적으로 제시하지 않는다.

RSS 일반 예제:

```python
import feedparser

url = "https://www.federalreserve.gov/feeds/press_monetary.xml"
feed = feedparser.parse(url)
if not feed.entries:
    raise RuntimeError("No entries; verify feed access and format")
for e in feed.entries[:5]:
    print(e.get("id") or e.get("link"), e.get("title"), e.get("published"))
```

공식 허용 HTML 파싱 예시:

```python
import requests
from bs4 import BeautifulSoup

url = "https://www.bea.gov/news/schedule"
res = requests.get(url, headers={"User-Agent": "AutoAxeResearch/1.0 your-email@example.com"}, timeout=15)
res.raise_for_status()
soup = BeautifulSoup(res.text, "html.parser")
rows = soup.select("table tr")
if not rows:
    raise RuntimeError("Table not found; inspect DOM before using values")
for row in rows[:10]:
    print(" ".join(row.stripped_strings))
```

HTML DOM 구조나 공표 제목이 바뀌면 **manual_review_required**로 전환. `429` 뒤 반복 재시도, `403` 우회, CAPTCHA/로그인 우회는 금지. CNN 지수·Google Maps 피자·Cboe 호가 화면을 무단 자동 스크래핑하지 않는다.

## 9. 수동 fallback & 검증

[Manual_Collection.md](./Manual_Collection.md)의 CSV 구조를 사용한다. 점수/가격/공개 기준시각/자산 정의·지연정보/출처·조회시각을 기록하고, 실제 데이터 이용 가능 시점보다 이전에 백테스트 신호를 생성하지 않는다. 무료 자동 수집이 어려운 경우가 있어도 **유료로 전환하지 않고 수동** 처리한다.

실행 예제: [examples/realtime_collector.py](../examples/realtime_collector.py) · [환경설정](../examples/.env.example).

## 10. 무료 API를 못 쓰는 경우: 수동 입력 명령

```bash
python docs/examples/manual_record.py --series CNN_FEAR_GREED --value 65 --unit index --source-url https://edition.cnn.com/markets/fear-and-greed --operator researcher --note "EXAMPLE only"
```

숫자 65는 **문법 예시**로 실제 공포·탐욕 점수가 아니다. 실제 입력 시 근거 화면을 확인하고 화면에 공개시각이 있으면 `--as-of 2026-11-22T20:00:00+09:00` 형식으로 입력한다. 없으면 비운다. 기본 출력 `auto_axe_manual_observations.csv`, 등록 직후 `unverified` 상태다. 자세한 컬럼·검증·품목 목록은 [Manual_Collection.md](./Manual_Collection.md).


## 11. PizzINT·CNN 지정 출처와 이전 yfinance 조사 기록

- PizzINT 출처: `https://www.pizzint.watch/`; 공개 데이터 URL `https://www.pizzint.watch/api/dashboard-data`. HTTP 200 JSON 응답과 필드 확인. 그러나 `/robots.txt`의 `Disallow:/api/`와 공개 API 이용 허용을 명시한 Terms의 결합 해석상 **접근 권한을 먼저 확인**. HTML 범위 외 스크래핑 금지. 그 전에는 PizzINT 화면에서 수동 기록.
- CNN 원본: `https://edition.cnn.com/markets/fear-and-greed`. CNN Terms는 자동화 데이터 추출/스크래핑을 금지하므로 명시적 허가 전 **스크래핑 코드 실행 금지·수동 입력**.
- Yahoo 시장 심볼 무료 검증 스크립트 (개인 연구용, 상용/재배포 권한은 별도):

```bash
python -m pip install yfinance
python docs/examples/yfinance_probe.py --period 5d --interval 1m
python docs/examples/yfinance_probe.py --websocket --ws-seconds 45
```


## 구리·은 및 Binance 롱숏 비율 추가 (2026-11-23)

- **구리:** Binance Futures `COPPERUSDT`, 내부 `COPPER_BINANCE_PERP`; **은:** `XAGUSDT`, 내부 `SILVER_BINANCE_PERP`. 두 종목 모두 실측 `TRADING / TRADIFI_PERPETUAL`, REST 1분봉 지원. 기존 Binance Futures `@aggTrade` 실시간 스트림의 구독 목록에 추가했다. USDT 표시 영구선물은 원자재 현물 또는 거래소 만기선물과 다르다.
- **공식 롱숏 비율 4종:** 전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율. Binance `/futures/data/*` 무료 공개 REST의 **최소 5분 집계**로 수집한다. 실시간 WS 틱이 아니며, Taker 매수·매도 비율은 포지션 롱숏 비율과 다르다.
- `python docs/examples/realtime_collector.py binance-live`: BTC Spot + 금·은·구리·WTI·Brent 5개 영구선물.
- `python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300`: 6개 Binance 선물 심볼의 롱숏·Taker 통계 5분 간격 조회.
- [상세 응답 검증과 API 구분](./Binance_Metals_LongShort_20261123.md) · [Python 수집기](../examples/realtime_collector.py).
