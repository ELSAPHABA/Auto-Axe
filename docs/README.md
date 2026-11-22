# Auto-Axe 시장 지표 수집 조사

> 조사 기준: **2026-11-22 (KST)** · 단계: 데이터 소스 탐색 및 수집 설계 (수집기 구현 전)

NH나무 OpenAPI 기반 퀀트 플랫폼 **Auto-Axe**의 외부 거시·심리·이벤트 지표를 수집하기 위한 자료다. **가격·금리의 시계열**, **발표·만기 일정**, **텍스트 기반 가이던스**, **실험적 OSINT 신호**를 분리하여 설계한다.

## 문서

- [Indicator_Data_Sources.md](./Indicator_Data_Sources.md): 요청한 **전체 지표별** 공식 출처, 실제 API/파일 경로, 수집 방식, 단위·갱신 주기, 상용 대안, 제약·출처 링크.
- [Collector_Design.md](./Collector_Design.md): 공급원 어댑터 설계, 수집 우선순위, 표준 스키마, 주기·시각·휴장일 처리, 백테스트 재현성, 운영·검증 체크리스트.

## 핵심 결론

| 구분 | 우선 선택 | 주의 |
|---|---|---|
| 미국 주식 공포·탐욕 | CNN 화면 및 자체 대체 지수 | CNN 공식 공개 API가 확인되지 않음; 비공식 JSON은 계약/변경 위험 |
| 기업 실적 가이던스 | SEC EDGAR 8-K/10-Q/10-K + 발표자료, 필요 시 LSEG | *기업 자체 전망*과 *애널리스트 컨센서스* 구별 |
| 금 | World Bank 월간, 제3자 spot API, 라이선스 LBMA | LBMA 공식 금 벤치마크의 사용·재배포 권리 확인 |
| WTI / Brent | EIA API (일별 현물) | CME 선물 근월물과 현물은 별개 |
| Dubai | IMF/FRED `POILDUBUSDM` (월별) | WTI/Brent 일별 데이터와 같은 빈도로 취급 금지 |
| VIX | Cboe 공식 EOD CSV | 실시간 값은 별도 상용 피드 |
| 미국 국채 | U.S. Treasury 수익률 곡선 / FRED `DGS*` | 국채 *수익률*과 개별 채권 *가격*은 다른 데이터 |
| 펜타곤 피자지수 | 공개 PizzINT/Pentagon.Pizza 관찰 | 검증된 금융 지표 아님, Google Maps 추출 약관 확인 |
| 금리·경제 발표 | FOMC·BLS ICS·BEA·Census 공식 달력 | 예정 시각 변경·미국 DST 대응 |
| 파생상품 만기 | OCC/Cboe·CME 상품별 공식 캘린더 | 모든 옵션·선물이 '셋째 금요일' 만기는 아님 |
| 미·일·영·유럽 정책금리 | Fed/FRED·BOJ·BoE·ECB 공식 데이터 | 정책 목표, 하한·상한, 실효금리를 별개로 모델링 |
| Bitcoin | Coinbase 공개 시장 데이터, 예비 공급원 Kraken | 거래소별 가격 차이 및 24×7 시간축 |

### 권장 실행 순서

1. **P0 (공식·기계 판독)**: FRED/Treasury, EIA, Cboe VIX 일별, BLS ICS, ECB/BoE/BOJ, Coinbase.
2. **P1 (정규화 필요)**: SEC 가이던스 이벤트 추출, 거래소별 만기 규칙, BEA/FOMC 일정 갱신.
3. **P2 (계약·품질 검토)**: CNN 원본 지수, 실시간 LBMA/VIX·Dubai, 컨센서스/가이던스 상용 데이터.
4. **실험 채널**: 피자지수·비공식 심리지표. 백테스트 핵심 신호에 즉시 투입하지 않는다.

**중요:** 이 문서는 데이터 공급원과 구현 경로를 조사한 설계서다. 모든 API의 실제 호출·인증·요금제 및 법적 재배포 권한까지 검증한 실행 완료 보고서는 아니다. 실서비스에 편입하기 전 공급자 문서와 약관을 다시 확인한다.

## 실시간·준실시간 수집 확장 (2026-11-22)

- [Real_Time_Data_Sources.md](./Real_Time_Data_Sources.md) — 요청한 모든 지표별 **실시간 API/WS/상용 시장 피드** 및 **API 부재 시 조건부 스크래핑** 가능성, 무료·유료 구분, 법적 제약, 데이터 지연을 표로 정리.
- [Realtime_Quickstart.md](./Realtime_Quickstart.md) — 설치·실행 커맨드, 공급원별 curl/WS/Python 예제, 공식 일정·공시 감시, 허용된 HTML 파싱, 유료 서비스 확장.
- [examples/realtime_collector.py](./examples/realtime_collector.py) — BTC 거래 WebSocket, 금 spot, SEC 8-K Atom, BLS ICS/실제 수치, FRED, EIA, Cboe VIX EOD를 stdout JSONL로 출력하는 **실행형 참조 스크립트**.
- [examples/requirements.txt](./examples/requirements.txt) · [examples/.env.example](./examples/.env.example) — 실행 환경과 비밀키 샘플.

> **주의:** 실시간 시장 시세와 단순 최신 API 결과는 서로 다르다. Cboe VIX/미 국채 현물/ICE Brent·WTI·Gold 선물/Platts Dubai의 진짜 실시간 값에는 별도 계약이 필요할 수 있다. CNN 비공식 점수와 Google Maps 기반 피자지수는 데이터 이용 권한 심사 전 운영 수집·자동주문 피처에서 제외한다. 예제는 주문 기능이나 DB를 변경하지 않으며, 실제 API 권한별 수신 테스트는 별도로 수행해야 한다.
