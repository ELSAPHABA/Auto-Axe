# Auto-Axe 실시간 수집 빠른 시작 (Python)

이 문서는 **API 키 없이 실행 가능한 수집기**부터 **키 발급 후 공식 데이터를 가져오는 방법**, **실시간 유료 시장 피드의 설정 방식**, **API가 없을 때 허용되는 HTML 스크래핑**까지 정리한다. 사용 전 [실시간 소스 상세 비교](./Real_Time_Data_Sources.md)를 읽을 것.

## 0. 무엇이 진짜 실시간인가?

| 명령/공급원 | 시간 특성 | API 키 | 운영 수준 |
|---|---|---|---|
| `coinbase` | 거래 발생 시 WebSocket 푸시 | 불필요 | 공개 BTC-USD 스트리밍 |
| `binance` | 거래 발생 시 WebSocket, 종료 1m 봉 | 불필요 | 공개 BTC-USDT 스트리밍, 지역 접근성 확인 |
| `gold` | 공급자 캐시가 있는 최근 현물 추정가 | 불필요 | 준실시간, LBMA 벤치마크 아님 |
| `sec-8k` | 신규 공시 Atom 확인 | 식별 User-Agent | 이벤트 준실시간; 가이던스 추출은 별도 |
| `bls-calendar` | BLS 공식 발표 예정표 | 불필요 | 스케줄 동기화 (수치 아님) |
| `bls-actual` | BLS 공식 발표 수치(배포 이후) | 등록 키 선택 | 발표 후 시계열 API, 제공 지연 가능 |
| `fred` | FRED 공개된 최신 시계열 | FRED 키 | 대개 일별/월별; 틱 아님 |
| `eia` | EIA 게시된 WTI/Brent 현물가격 | EIA 키 | 일별; 틱 아님 |
| `vix-eod` | Cboe 공식 VIX 일별 OHLC CSV | 불필요 | **종가/과거 EOD**; 틱 아님 |

**실시간 유가·금 선물·국채 실시간 현물·VIX 지수는 유료 시장데이터 계약이 필요할 수 있다.** 1분 폴링만으로 공식 EOD 값을 실시간화할 수 없다.

## 1. 설치

Python 3.11 이상에서 실행 권장 (Windows PowerShell / Linux/macOS).

```bash
git clone https://github.com/ELSAPHABA/Auto-Axe.git
cd Auto-Axe
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r docs/examples/requirements.txt
Copy-Item docs/examples/.env.example .env
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -r docs/examples/requirements.txt
cp docs/examples/.env.example .env
```

`.env`에 SEC 신고용 실제 연락처 및 선택한 API 키를 입력한다. **이 예제는 stdout(JSON Lines)으로만 출력**, 데이터베이스와 주문 API에 연결하지 않는다. 수집 결과는 콘솔에서 확인하거나 파일로 리디렉션할 수 있다. Windows PowerShell에서 파일 인코딩은 UTF-8로 설정 권장.

## 2. 무료 공개 실시간 BTC WebSocket

### Coinbase Exchange BTC/USD (실거래 기반 ticker)

```bash
python docs/examples/realtime_collector.py coinbase
```

- WebSocket `wss://ws-feed.exchange.coinbase.com`.
- 로그인 없이 `{"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker","heartbeat"]}` 보냄.
- `ticker`만 가격 이벤트로 기록. `heartbeat`은 연결 상태/누락 감시용.
- 예시 출력 모양(값은 **가상의 형식 예시**, 실제 시세 아님):
  ```json
  {"provider":"coinbase","series":"BTC-USD.trade_ticker","value":"100000.00","source_event_at":"2026-11-22T10:00:00Z","received_at":"2026-11-22T10:00:00.120000+00:00","trade_id":12345,"quote":"USD"}
  ```
- 실패 시 지수 백오프 재접속; 서비스 운영 단계에서는 거래소 Sequence Number로 gap을 검증하고 REST 캔들/체결을 백필.
- 공식: [Coinbase WebSocket Overview](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview).

### Binance Spot BTC/USDT (체결 + 1분 확정봉)

```bash
python docs/examples/realtime_collector.py binance
```

- 공개 market-data-only `wss://data-stream.binance.vision/stream?streams=btcusdt@trade/btcusdt@kline_1m`. 정규 WS `wss://stream.binance.com:9443` 경로도 있으나 지역 제한 가능.
- 1분봉 `k.x == true`일 때만 닫힌 봉으로 기록; 진행 중 봉을 확정봉으로 백테스트에 사용하지 않음.
- 서버 ping에 라이브러리가 프로토콜 pong 응답하도록 두고, 24시간 연결 수명에 대비 재접속. 메시지/스트림/접속 시도 제한 준수.
- **BTCUSDT는 BTCUSD가 아니다.** 통화 페그 이탈과 거래소별 시세 차이를 별도 관리.
- 공식: [Binance WS Streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md).

둘 다 아래처럼 출력 저장 가능:

```bash
python docs/examples/realtime_collector.py coinbase >> btc_usd.jsonl
```

## 3. 금 현물가격 준실시간 REST

```bash
curl "https://api.gold-api.com/price/XAU"
python docs/examples/realtime_collector.py gold
python docs/examples/realtime_collector.py gold --interval 60
```

- 응답 `price`와 공급자 제공 `updatedAt`을 보존. 같은 타임스탬프·값 반복이면 DB에서 중복 제거.
- **호가 데이터/시세 확정성을 보장하지 않는 제3자 spot estimate**이며 COMEX GC 선물이나 LBMA AM/PM 벤치마크가 아님.
- 시세가 30초마다 바뀌는 것으로 알려져 있어도 공급자에서 **정식 1초 틱**을 제공한다는 의미는 아니다.
- [Gold API Docs](https://gold-api.com/docs) / [Terms](https://gold-api.com/terms).

## 4. 기업 가이던스: SEC 실시간에 가까운 신규 공시 감시

`.env`에 SEC 식별 가능한 이메일을 넣고 시작:

```dotenv
AUTO_AXE_USER_AGENT=AutoAxe Research your-real-email@example.com
```

```bash
python docs/examples/realtime_collector.py sec-8k --interval 90
```

- 공식 SEC EDGAR 최근 공시 **Atom** `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=exclude&count=100&output=atom`.
- `id`별 신규 감지 → `8-K`에서 `Item 2.02` 실적공시와 `Exhibit 99.1` 실적 발표자료 확인 → `outlook/guidance/expect` 문구와 예상 EPS/매출/마진/CapEx 추출.
- **예제는 새 공시 탐지만 구현.** 가이던스 텍스트/숫자 추출을 자동으로 수행했다고 주장하지 않는다. 프로덕션은 accession 파싱, `data.sec.gov/submissions/CIK##########.json`, 원문 `www.sec.gov/Archives/edgar/data/...` 및 `primaryDocument`/첨부 파일 수집·검증 추가.
- 응답 feed 첫 수집 시 기존 최대 100개가 신규로 보일 수 있으므로, 프로덕션에서 bootstrap watermark와 영구 상태 저장 필요.
- 최종 가이던스 모델: `issuer/CIK`, `fiscal_period`, `guidance_metric`, `basis(GAAP/adjusted)`, `range_low/range_high`, `filed_at`, `first_seen_at`, `accession`, `exhibit_url`, `confidence/reviewer`. 컨센서스와 별개 테이블.
- SEC Fair Access: 자신을 식별하는 User-Agent, 초당 10요청 이하 통합 한도, 403/429 시 중단·백오프. [공식 RSS](https://www.sec.gov/about/rss-feeds), [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
- **데이터가 공시를 통해 공개될 때까지 기다려야** 하며, 실적 공시보다 먼저 나오는 기업 IR 발표를 잡으려면 해당 기업의 공식 RSS/공지/보도자료 페이지 어댑터를 추가.

## 5. 금리·경제지표 발표 예정 및 실제 결과

BLS 예정 캘린더:

```bash
python docs/examples/realtime_collector.py bls-calendar
python docs/examples/realtime_collector.py bls-calendar --interval 3600
```

- 공식 `https://www.bls.gov/schedule/news_release/bls.ics` 파싱. `UID`, `DTSTART`, `STATUS`로 변경 탐지.
- CPI, PPI, 고용보고서 **예정 날짜**이지 실제 CPI 수치가 아니다.

BLS 실제 지표 값(원 기관이 게시한 이후):

```bash
python docs/examples/realtime_collector.py bls-actual
python docs/examples/realtime_collector.py bls-actual --interval 1800
```

- 공식 `POST https://api.bls.gov/publicAPI/v2/timeseries/data/`.
- `BLS_SERIES=CUUR0000SA0,CES0000000001,LNS14000000` 예시: CPI-U 전체, 총 비농업부문 취업자 수, 실업률. 단, CPI가 발표되는 관측월과 근로자 수 관측월은 다르다.
- `BLS_API_KEY` 등록 시 일일 쿼터 증가. 공개 문서상 등록키 500쿼리/일, 무키 25쿼리/일로 **1초 폴링은 불가**. 발표 근접 시 15~30초 짧은 구간에서만 임시 폴링, 나머지는 15~60분 단위 권장.
- 빠른 실시간 경제 surprise가 목표면 [Trading Economics Calendar Streaming](https://docs.tradingeconomics.com/economic_calendar/streaming/) 계약 후 actual/forecast/previous를 수신. BLS 보도자료 `https://www.bls.gov/news.release/cpi.htm` 등 공식 HTML은 허용 범위 내에서 파싱 가능. API 갱신 시점과 실제 최초 발표는 일치 보장 안 됨.
- [BLS API](https://www.bls.gov/developers/api_signature_v2.htm) · [BLS FAQ](https://www.bls.gov/developers/api_faqs.htm).

### 허용된 공개 HTML을 파싱할 때

공개 사이트의 **이용약관·robots.txt·자동화 정책에서 허용되는 경우에만** 아래 패턴을 개별 페이지에 적용한다. 이 예는 **선별된 공지 제목만 추출**하며, 금융 시세 사이트의 제한을 우회하지 않는다.

```python
import requests
from bs4 import BeautifulSoup

url = "https://www.bea.gov/news/schedule"
response = requests.get(
    url, headers={"User-Agent": "AutoAxeResearch/0.1 contact@example.com"},
    timeout=(5, 15)
)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")
for row in soup.select("table tr")[:20]:
    print(" ".join(row.stripped_strings))
```

설치: `python -m pip install beautifulsoup4`. **선택자가 비거나 구조가 바뀌면 실패로 기록**하고 공식 일정 표와 대조한다. 홈페이지 공지·캘린더에는 `ETag/If-Modified-Since` 지원 시 조건부 GET 적용, 403/429·CAPTCHA는 우회하지 말고 중단. 2026년 발표 시간대 ET와 KST 변환에는 `zoneinfo.ZoneInfo("America/New_York")` 사용.

## 6. FRED / EIA / Cboe 공개 데이터 (공식값 교차검증)

FRED 무료 API 키: [발급 안내](https://fred.stlouisfed.org/docs/api/api_key.html).

```bash
python docs/examples/realtime_collector.py fred --series DGS10
python docs/examples/realtime_collector.py fred --series DFEDTARU
python docs/examples/realtime_collector.py fred --series DFEDTARL
python docs/examples/realtime_collector.py fred --series DFF
python docs/examples/realtime_collector.py fred --series POILDUBUSDM
```

EIA 무료 키: [Open Data](https://www.eia.gov/opendata/).

```bash
python docs/examples/realtime_collector.py eia --series PET.RWTC.D
python docs/examples/realtime_collector.py eia --series PET.RBRTE.D
```

Cboe 공식 EOD:

```bash
python docs/examples/realtime_collector.py vix-eod
```

- FRED/DGS·미 국채 수익률은 **일별**이고 WTI/Brent EIA 현물도 **일별**이다.
- Dubai `POILDUBUSDM`는 **월평균**으로 원천 출처 IMF, FRED 반영 지연 존재.
- 미국 통화정책 `DFEDTARL`/`DFEDTARU`는 정책 **목표구간 하한/상한**, `DFF`는 **실효금리**. 정책 결정 속보는 [FOMC 성명](https://www.federalreserve.gov/newsevents/pressreleases/2026-press-fomc.htm) 감시.
- 데이터가 오늘 검색됐다고 `source_event_at`을 현재시간으로 바꿔 저장하면 안 됨.

## 7. 유료 실시간 시세로 확장

### Databento (CME Globex 예제)

```bash
python -m pip install databento
```

```python
import os
import databento as db

live = db.Live(key=os.environ["DATABENTO_API_KEY"])
live.subscribe(dataset="GLBX.MDP3", schema="trades",
               stype_in="parent", symbols="ES.FUT")
live.add_callback(print)
live.start()
live.block_for_close(timeout=30)
```

`ES.FUT`는 공식 라이브 Quickstart 심볼. WTI `CL`, Gold `GC`, CBOT 국채 `ZN` 등을 사용하려면 실제 지원 instrument ID를 조회하여 entitlement 확인. ICE Brent 원계약은 별도 거래소/피드다. [공식 SDK](https://databento.com/docs/quickstart/live).

### Massive Futures (WebSocket: 계약형)

- 실시간 `wss://socket.massive.com/futures`, 지연 `wss://delayed.massive.com/futures`. 인증/구독은 해당 고객 플랜 문서에 따라 수행.
- REST 월물 탐색: `GET https://api.massive.com/futures/v1/contracts?product_code=CL` + API key; 단순 `CL` 연속물 대신 실제 거래 월물 코드 결정.
- WS 이벤트 채널 `T.<contract>` 체결, `Q.<contract>` 호가. 예 `T.CLZ6`처럼 정확한 월물을 지정하되 계약 목록에 있는 **유효 기간·종목 확인 후에만** 사용.
- 구독 예시 메시지(실제 데이터가 있는 플랜/월물로 수정):
  ```json
  {"action":"auth","params":"YOUR_API_KEY"}
  ```
  ```json
  {"action":"subscribe","params":"T.CLZ6"}
  ```
- [Massive 공식 선물 WS](https://massive.com/docs/websocket/futures/trades), [WebSocket 연결 방식](https://massive.com/knowledge-base/article/how-can-i-connect-to-a-massive-websocket). 실시간 권한·거래소별 라이선스·비표시/재배포는 별도.

### Trading Economics (경제 캘린더 실시간 스트림)

```bash
python -m pip install tradingeconomics
```

```python
import os
import tradingeconomics as te

te.login(os.environ["TRADING_ECONOMICS_API_KEY"])
def on_event(message):
    print(message)  # normalize actual / forecast / previous / date / calendarId

te.subscribe("calendar")
te.run(on_event)
```

계정 플랜이 calendar streaming을 지원하는지 확인한다. `te.run`의 callback 및 실제 메시지 schema는 사용 중인 패키지 버전과 [공식 Streaming 문서](https://docs.tradingeconomics.com/economic_calendar/streaming/) 기준 테스트. 무료 demo 값으로 운영 신호를 생성하지 말 것.

## 8. 정책금리·파생만기·피자지수의 즉시 활용 방식

- **Fed/BOJ/BoE/ECB 금리**: 결정 예정 시간을 캘린더로 보관 → 해당 발표 페이지 RSS/HTML를 공식 허용 빈도로 감시 → 정책 성명에서 변경 수치 및 effective date 파싱 → [FRED / BOJ API / BoE IUDBEDR / ECB DFR](./Indicator_Data_Sources.md)로 교차 검증. 결정문 발표 이벤트는 초 단위, 정적 공식 금리 수준은 매초 변경되지 않음.
- **옵션/선물 만기**: OCC/OIC·Cboe·CME 공식 계약 캘린더에서 명목 만기일·최종거래일·처리일·결제일 별도 기록하고 **`remaining_seconds = expiry_timestamp - now_utc`**만 실시간 계산. 예: 2026-06-19 명목 옵션 만기일의 OCC 처리일은 Juneteenth로 **6월 18일**인 경우가 있어 [OCC Memo 56694](https://infomemo.theocc.com/infomemos?number=56694) 준수.
- **피자지수**: Google Places Popular Times는 정식 정량 수집용 REST API가 없고 [Google 정책](https://developers.google.com/maps/documentation/places/web-service/policies)상 콘텐츠 외부 추출·저장이 제한됨. [pentagon.pizza](https://www.pentagon.pizza/) 참고 링크만 제공하고, 원자료 수집은 **공급자로부터 계약/서면 허락**을 받은 후 구현한다.
- **CNN 공포·탐욕지수**: 비공식 JSON `https://production.dataviz.cnn.io/index/fearandgreed/graphdata`는 공식 보장 API가 아니다. 접근·사용권 확인 후에만 제한적 검증과 5~15분 스냅샷이 가능. 권리 미확인 상태에서는 자동화 코드로 기본 수집하지 않음. 자체 심리지표 구축은 [실시간 소스 보고서](./Real_Time_Data_Sources.md) 참조.

## 9. 운영 전 점검표

1. provider별 응답 10개 이상 실제 받아 필드·source timestamp, 지연 P95, timezone, 가격 단위·호가통화 확인.
2. WS 끊김·재접속/중복처리·시퀀스 gap/REST 백필을 수집기별로 구현. 제공자 간 환산 프록시와 원상품을 병합 금지.
3. API key는 `.env`/비밀 저장소에만 저장하고 stdout·URL 로그에서 제거. `.env` Git 커밋 금지.
4. 생산 DB 키: `provider, series, venue, contract, source_event_at, revision`와 `received_at` 둘 다 유지. 첫 공개 시점을 역산하거나 hindsight 수정치로 백테스트 금지.
5. 공급자의 **non-display algorithmic use**(자동매매 신호), 자체 화면 표시, 제3자 재배포, 과거 저장 라이선스 각각 확인.
6. 시장 데이터가 stale/unlicensed이면 주문 엔진에 위험 차단을 걸고, 시각·지연·사용권 상태를 대시보드에 표시.

> 이 예제는 **시장 데이터 수집 동작을 확인하는 PoC**다. 주문 엔진에 즉시 연결하거나 값의 실시간성과 법적 사용권을 자동 보증하지 않는다.
