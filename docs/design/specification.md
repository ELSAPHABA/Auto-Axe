# Auto-Axe 시스템 설계 명세서

> 기준일: 2026-11-24 · 설계 초안. 기존 지표 수집 명세를 통합한 목표 아키텍처이며 운영 시스템 구현 완료를 의미하지 않는다.

## 1. 목적 및 범위

Auto-Axe는 NH나무 OpenAPI 기반 알고리즘·패턴 매매 퀀트 시스템을 목표로 한다. 현재 저장소에서 확인되는 구현 범위는 무료 시장 데이터 수집 및 검증용 Python 예제다. 본 설계는 수집, 정규화, 저장, 피처 산출, 분석 및 향후 매매 연동의 경계를 정의한다. 주문 API 상세, 전략 알고리즘, 배포 인프라, DB 제품, UI 기술은 아직 확정하지 않는다.

- [기능 명세](../function/specification.md)
- [프론트엔드 디자인 명세 (Live3x 레퍼런스)](./frontend.md)
- [무료 데이터 수집 정책](../indicator-collection/Free_Data_Collection.md)
- [수집기 설계 원문](../indicator-collection/Collector_Design.md)

## 2. 논리 아키텍처

```mermaid
flowchart LR
  A[시장 WebSocket] --> C[수집 어댑터]
  B[REST / 공식 파일 / 공시] --> C
  H[허용 HTML / 수동 입력] --> C
  S[스케줄러] --> C
  R[소스 정책 및 권한 레지스트리] --> C
  C --> N[정규화]
  N --> Q[품질 검증 및 중복 제거]
  Q --> D[(관측값 / 이벤트 저장소)]
  Q --> E[오류 및 검수 대기]
  D --> F[피처 계산]
  F --> P[(파생 지표 저장소)]
  D --> V[분석 및 백테스트]
  P --> V
  V --> G[전략 및 리스크 검증 - 향후]
  G --> O[NH나무 주문 연동 - 향후]
```

| 계층 | 책임 |
|---|---|
| 소스 레지스트리 | provider, series_id, 상품 정의, 수집 방식, 주기, 권한 및 활성화 상태 |
| 수집 어댑터 | WS 구독, REST 조회, 공식 문서 파싱, 승인형 HTML 추출, 수동 입력 |
| 스케줄러 | 스트림 수명 관리, 주기 실행, 발표 예정 시각 기반 실행, 1Hz 로컬 샘플링 |
| 정규화·검증 | 단위·통화·시간대·상품 유형, 필수 필드, 순서·중복·결측·지연 검사 |
| 저장소 | 원본 관측, 이벤트, 정정 이력, 재무 스냅샷, 파생 피처 |
| 피처 엔진 | 이동평균, 고저가, 위칭 플래그·DTE 등 재현 가능한 로컬 계산 |
| 분석 | 시계열 조회, 대시보드 및 point-in-time 백테스트 목표 |
| 매매 연동 | 향후 별도 설계; 데이터 품질 및 리스크 검증과 분리 |

## 3. 수집 파이프라인

1. 소스 레지스트리에서 활성화 여부, 비용 0, 권한, 호출 제한 및 상품 정의를 확인한다.
2. 이벤트 기반 WS 또는 주기 기반 API·공식 파일을 우선 사용한다. 허용된 경우에만 HTML 파싱을 실행한다.
3. 원본 응답의 필드·시간·단위를 정규화한다. 원본 보관은 허용 범위에 한정한다.
4. 스키마 오류, 결측, 역순, 중복, 세션 변경, 지연 및 정정을 검증한다.
5. 유효 관측값과 상태를 적재한다. 오류는 검수 대기 또는 결측 상태로 기록한다.
6. 확정봉·새 발표·새 관측 등 피처별 트리거에 따라 파생 지표를 계산한다.
7. 분석 소비자는 값뿐 아니라 원본 시각, 품질, 권한 상태를 함께 조회한다.

### 3.1 스트림

Binance Spot BTCUSDT 및 TradFi Futures 5종은 독립 상품으로 구독한다. 선물 WS는 현재 검증 문서의 `wss://fstream.binance.com/market/stream?streams=...` 경로를 사용한다. 재연결, ping/pong, 누락 구간 및 중복 처리를 구현 대상으로 둔다.

미국 주식·ETF는 yfinance AsyncWebSocket 수신 캐시와 1Hz 샘플러를 분리한다. 샘플러는 monotonic clock 기반으로 동작하며 새 메시지가 없으면 기존 원본 시각을 유지한다. 누적량 감소·거래일 변경은 리셋 검증 대상으로 처리한다. 공급자의 1초 전송이나 무지연을 보장하지 않는다.

### 3.2 스케줄링

| 작업 | 권장 주기 |
|---|---|
| Binance 시세 | 체결 이벤트 |
| Binance 롱숏·Taker 통계 | 5분 집계, 기본 300초 조회 |
| yfinance VIX·국채 | 1~5분 최신봉 |
| 미국 주식 누적 거래량 | WS 이벤트 + 로컬 1초 |
| PER·PBR | 일별 |
| ROE | 실적 발표 후 |
| SMA·EMA·고저가 | 해당 봉 확정 후 |
| Treasury·EIA·Cboe 일별 | 게시 완료 후 |
| SEC/IR 공시 | 허용 범위 내 60~120초 |
| 경제 발표 일정 | 일 1~4회 및 발표 전 확인 |
| 실제 발표·정책 결정 | 예정 시각 전후 집중, 호출 제한 준수 |
| 만기·위칭 | 주간 및 변경 공지, 해당 주 일별 확인 |
| DRAM 모듈 | 일 1회 점검, 주간 원본 갱신만 적재 |
| SEIBro·CNN·PizzINT·네이버 | 권한에 따른 수동 또는 승인형 수집 |

주기는 프로젝트 제안이며 공급자의 갱신 보장이 아니다. [상세 정책](../indicator-collection/Free_Data_Collection.md).

## 4. 데이터 모델

논리 스키마이며 특정 DB 엔진 확정이 아니다. 기존 SQL 예시는 [Collector_Design.md](../indicator-collection/Collector_Design.md)를 참조한다.

| 엔터티 | 주요 필드 |
|---|---|
| source_registry | provider, series_id, instrument_type, method, source_url, frequency, cost, terms_check_at, permission_status |
| indicator_observations | provider, series_id, symbol/contract_code, value, unit, quote_currency, venue, period_label, observation_at, published_at, first_seen_at, received_at, revision_id, status, source_url |
| stock_volume_samples | symbol, day_volume, source_event_at, last_received_at_utc, sampled_at_utc, source_age_sec, receive_age_sec, data_status, market_hours |
| corporate_guidance | cik/ticker, accession, filing_url, fiscal_year/quarter, metric, gaap_or_adjusted, low/high, first_seen_at, review_status |
| fundamental_snapshots | symbol, metric, value, unit, fetched_at_utc, financial_period_end, published_at_utc, earnings_basis |
| event_calendar | scheduled_at, released_at, first_seen_at, actual/forecast/previous, expiry_date, last_trade_at, processing_at, settlement_at, source_url |
| witching_events | event_type, candidate_date, effective_session_date, family_status, contract_refs, verified_at_utc, revision |
| technical_indicators | symbol, interval, indicator, window, value, close_basis, bar_closed_at_utc, calculated_at_utc, is_final_bar, warmup_complete |
| collection_runs | adapter, started_at, finished_at, result_status, error_type, record_count (제안) |

### 4.1 식별 및 정정

- 원본 상품과 공급자별 시계열을 분리한다. 현물/영구선물/만기선물, USD/USDT, 정규장/시간외를 혼합하지 않는다.
- 관측값은 공급자·시계열·원본 관측시각·계약/종목·집계기간을 고려한 복합 식별자를 사용한다. 정정은 revision으로 보존한다.
- 1Hz 거래량 샘플은 종목과 샘플 시각으로 식별한다. DRAM은 provider + series_id + source_updated_at을 기본 키로 한다.
- 원본 시각 미확인 시 null을 유지한다. 수신 시각으로 대체하지 않는다.

### 4.2 시간 및 백테스트

UTC 저장, 미국 동부시간 DST 및 거래소 세션 달력 적용, DRAM GMT+8 원본 시각 보존. 최초 공개와 실제 수집 시각 중 늦은 보수적 시점 이후에만 피처를 사용할 수 있게 한다. 수정값, 현재 재무 스냅샷, 미확정봉을 과거에 소급 적용하지 않는다.

## 5. 장애 대응 및 보안

- 429는 Retry-After, 5xx는 지수 백오프, 403·CAPTCHA·권한 실패는 우회 없이 중단한다.
- 동일 정의의 허용된 무료 소스만 failover 대상으로 사용한다. 다른 상품은 별도 참고 시계열이다.
- WS 연결 종료는 disconnected, 신규 데이터 없음은 no_update/stale, 최초 미수신은 no_data로 구분한다.
- HTML 구조 변경·필수 필드 누락은 성공 처리하지 않는다. 수동 검수 및 결측으로 전환한다.
- API 키는 환경변수 등 비밀 관리 경로를 사용하고 로그·저장소에 노출하지 않는다.
- 권한 미확인 데이터의 자동 적재·재배포·자동매매 사용은 활성화하지 않는다. 피자지수는 자동 주문 신호로 사용하지 않는다.
- 향후 주문 계층은 오래된 데이터 차단, 중복 주문 방지, 리스크 한도, 비상 정지 및 모의 검증을 별도 명세로 확정해야 한다. 현재 주문 구현은 확인되지 않는다.

## 6. 구현 및 검증 단계

| 단계 | 범위 | 상태 |
|---|---|---|
| 1 | Binance 시세·롱숏, yfinance 일부 분봉, Treasury 수집 예제 | 기존 PoC 및 일부 실측 검증 |
| 2 | 소스 레지스트리, 스케줄러, 저장소, 품질 검증 통합 | 목표 설계 |
| 3 | 주식 1Hz 누적량, 재무·기술지표, Nasdaq 연동, DRAM·SEIBro, 위칭 | 상세 문서화; 운영 구현 및 필요한 실측·권한 확인 미완료 |
| 4 | 분석·백테스트 및 전략 검증 | 목표 설계 |
| 5 | NH나무 매매 연동 | 별도 요구사항 확정 필요 |

단위 테스트는 필드 파싱·정규화·피처 계산, 통합 테스트는 연결 종료·중복·정정·휴장·권한 실패를 포함한다. 실시간 후보는 실제 장중 수신 빈도와 지연을 측정한다. [실행 예제](../examples/realtime_collector.py) · [검증 가이드](../indicator-collection/Realtime_Quickstart.md).
