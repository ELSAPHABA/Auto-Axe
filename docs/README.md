# Auto-Axe 데이터 수집 설계 — 무료 소스 전용

> **2026-11-22** · `Auto-Axe`(NH나무 OpenAPI 퀀트 플랫폼) 시장 데이터 수집 조사 문서. **모든 유료 데이터 피드·구독은 제외**한다.

## 선택 원칙

**1. 무료 API / WebSocket / 공개 CSV → 2. 이용약관상 허용된 RSS·Atom·ICS·HTML 스크래핑 → 3. 수동 입력**.

자동 수집 가능한 무료 원본이라도 일별·월별 공표 데이터의 갱신 빈도를 초 단위로 올릴 수 없다. 또한 *웹에 표시된다*고 *자동 추출·저장 권한이 있다*는 뜻은 아니다. 원본 값과 대체 프록시 상품은 섞지 않는다.

## 문서 바로가기

- [Free_Data_Collection.md](./Free_Data_Collection.md) — **최신 마스터 명세**: 미국 주식 공포·탐욕, 기업 가이던스, 금, WTI·Brent·Dubai, VIX, 미 국채, 피자지수, 경제 발표·실제값, 파생 만기, 미·일·영·유로존 정책금리, 비트코인 **전체 16개 영역**을 무료 API → 허용 스크래핑 → 수동으로 분류하고 URL·주기·제약을 상세 설명.
- [Realtime_Quickstart.md](./Realtime_Quickstart.md) — 설치/실행, 공개 BTC WebSocket, 무료 Gold API, SEC, BLS, FRED/EIA 참고, 공식 RSS·HTML 등 구현 가이드.
- [Manual_Collection.md](./Manual_Collection.md) — 무료 자동 수집 불가능한 지표의 수동 목록·입력 필드·CSV 형식.
- [Collector_Design.md](./Collector_Design.md) — 수집 어댑터/표준 스키마/파이프라인 장애·데이터 수정 및 최초 공개 시점의 백테스트 처리.
- [Indicator_Data_Sources.md](./Indicator_Data_Sources.md), [Real_Time_Data_Sources.md](./Real_Time_Data_Sources.md) — 무료 전용 요약 색인(마스터 명세의 보조자료).

## 코드

- [examples/realtime_collector.py](./examples/realtime_collector.py): 실시간 BTC 공개 WS, 금 최근가격, SEC Atom, BLS ICS 및 실제값, FRED/EIA/Cboe 공개값 출력.
- [examples/manual_record.py](./examples/manual_record.py): API·허용 스크래핑이 안 되는 수치의 **수동 CSV 한 행 등록**.
- [examples/requirements.txt](./examples/requirements.txt) · [examples/.env.example](./examples/.env.example): 무료 API용 Python 의존성·선택적 무료키.

## 빠른 실행

```bash
python -m pip install -r docs/examples/requirements.txt
python docs/examples/realtime_collector.py coinbase
python docs/examples/realtime_collector.py gold --interval 60
```

수동 입력 예시(값은 예시이며 실제 관측 아님):

```bash
python docs/examples/manual_record.py --series CNN_FEAR_GREED --value 65 --unit index --source-url https://www.cnn.com/markets/fear-and-greed --operator researcher --note "EXAMPLE only"
```

## 데이터 가용성 요약

| 무료 자동 수집 | 공개 소스 있으나 장중 실시간이 아님 | 기본 수동 |
|---|---|---|
| BTC Coinbase/Binance WS, 금 최근가격, SEC/IR 공시, BLS·BEA 공식 발표, 정책금리 이벤트·공식 시계열 | WTI/Brent EIA 일별 현물, Dubai 월평균, VIX Cboe 일별, Treasury 일별 수익률, 파생 만기 달력 | CNN 원본 공포·탐욕, 피자지수, 장중 VIX·국채 현물·원유 가격, 불확실한 컨센서스 |

> 작성된 코드는 **PoC**로, GitHub에 저장 및 Python 문법 검증을 거쳐야 한다. 별도 등록·개인 키가 필요한 무료 API의 실제 인증이나 24시간 무중단 동작을 보장하지 않는다. 주문 기능은 변경하지 않는다.


## 사용자 지정 출처 및 yfinance 실증 (2026-11-22)

- 피자지수 수집 대상: **[PizzINT](https://www.pizzint.watch/)**. 공개 JSON `/api/dashboard-data`는 실제 응답하지만 robots 정책과 Terms의 권한 확인 전 자동화하지 않으며, HTML 스크래핑은 API 범위 밖 금지.
- 미국 주식 공포·탐욕지수 수집 대상: **[CNN International](https://edition.cnn.com/markets/fear-and-greed)**. CNN 약관의 스크래핑 금지 때문에 승인 전 수동.
- [YFinance_Data_Validation.md](./YFinance_Data_Validation.md): `^VIX`, `^TNX`, `CL=F`, `BZ=F` 일봉/1분봉 직접 조회 성공. **실시간 무지연 아님(확인 불가; 원유 Yahoo Delayed Quote)**; 진짜 Dubai유 일별 심볼 미확인.
- [examples/yfinance_probe.py](./examples/yfinance_probe.py): yfinance 무료 라이브러리의 최근 분봉·메타데이터·WS 구독 가능성을 검증하는 별도 **테스트 전용** 스크립트 (`pip install yfinance`).
