# Frontend 기술 스택

> [기존 Live3x 레퍼런스 디자인](../design/frontend.md)의 레이아웃과 상태 의미를 구현하기 위한 기술 선택이다. 원본 브랜드·이미지·코드 복제 없음.

## 1. 선택

아래 기술 중 ELK.js만 자동 레이아웃 선택 사항이며 나머지 UI 구현/검증 라이브러리는 기본 필수다. OpenAPI 3.1 → openapi-typescript 생성 타입을 사용하고 React Flow 그래프는 [versioned JSON Schema](./contracts.md) §2에 맞춰 변환한다. 금융 원장 금액은 문자열로 취급한다.

| 기술 | 책임 |
|---|---|
| React + TypeScript + Vite | SPA, 정적 배포, strict 타입 |
| React Router | 홈/상세/그룹/Workflow/예측/백테스트/운영 |
| TanStack Query | 서버 상태, query key, cache invalidation, polling fallback |
| Zustand | 캔버스 편집 draft, UI 전역 토글·레이아웃, 세션 중 편집 상태 |
| Tailwind CSS + CSS variables | Live3x 스타일의 다크 토큰, 간격·반응형·상승/하락 색 |
| @xyflow/react (React Flow) | 사용자 노드·포트·엣지, 드래그, zoom, minimap, nested UI |
| ELK.js | 선택적 자동 레이아웃(실행 순서를 변경하지 않음) |
| TradingView Lightweight Charts | 캔들·거래량·SMA·EMA·고저가 overlay |
| Apache ECharts | 비율막대, 통계, 유사 패턴, calibration, 백테스트 |
| TanStack Table + Virtual | 대규모 표·로그·종목 목록 가상화 |
| React Hook Form + Zod | 설정 UI, 입력 유효성; 서버 검증이 최종 |
| Vitest / Testing Library / Playwright | 단위·접근성·통합 UI 테스트 |

SSR/Next.js는 초기 금융 내부 대시보드 요구에 비해 복잡성이 커 Vite SPA를 선택한다. 차트 라이브러리별 라이선스/NOTICE·TradingView attribution 요구사항을 확인하고 UI에 반영한다. paid React Flow Pro/차트 데이터 구독을 필수화하지 않는다.

## 2. 페이지 및 구성

| 라우트 | 주요 구성 |
|---|---|
| / | 시장 온도계, 카테고리 시세카드, sparkline, 글로벌 롱숏 토글, 활성 Workflow 수 |
| /market/:instrumentId | 가격·캔들·재무·거래량·고저가·롱숏 패널 및 원본 정의 |
| /indicators | 거시·산업·일정·심리 지표, 신선도 |
| /groups | 구성/가중치/버전, 집계 수익률·breadth 및 비교 |
| /workflows | 활성/모의/실행 상태, 참조 의존성·삭제 제약 |
| /workflows/:id/edit | 팔레트, 노드 캔버스, 조건 inspector, AND/OR/Fork/Join, 버전 검증 |
| /runs/:runId | 실제 경로·조건 raw/effective·hit_count·reset_epoch·이력·중단 |
| /strategies/friday-close | 확률·예상 수익률·하방 위험·유사 주·모델 상태·cutoff |
| /backtests/:id | 성과·비용·drawdown·거래 목록·재현 manifest |
| /portfolio, /settings | 제한 계좌 조회, 수집 상태, MCP 외부 접속·권한·감사 |

공통 컴포넌트: QuoteCard, SeriesChart, RatioBar, DataStatus, SourceLabel, WorkflowSummary, ConditionBadge, ResetCyclePanel. 상승은 빨강, 하락은 파랑, 상태는 색상+텍스트/아이콘. 시세 기준 시각과 단위·계약·품질·권한을 노출한다.

## 3. 편집기

모드 enum 및 Coordinator 설정(priority, 1회/일별 최대 매수·매도 수량/금액, risk profile, approval scope)은 backend DTO에 따른다. PAPER_LOCAL/PAPER_BROKER 구분, 갱신 generation 상태·source freshness·fallback 표시 및 CONFLICT_HELD/예약/한도 사유를 제공한다. LIVE 별도 승인 필요.

React Flow 그래프는 backend graph schema를 투영한다. node_id, type, schema_version, config, input/output port, edge source/target handle을 저장하고 UI 좌표/viewport는 별도 presentation metadata로 보존한다. 문자열 표현식을 eval하지 않는다. node catalog와 허용 연결·파라미터 schema는 서버에서 제공. 로컬 연결 검사(타입/필수 입력/순환)와 서버 validation을 분리한다. import/export는 버전 포함 JSON, 검증/참조 삭제 제약, undo/redo, autosave draft, optimistic concurrency. 하위 Workflow는 조건 포트만 노출하고 배포 버전을 고정한다. 노드 편집이 활성 실행 상태를 변경하지 않는다.

조건 설정: LATCHED N회, hold_until, CONTINUOUS, 재무장/중복 방지; 1/5/20/N 거래일 reset 및 거래소 달력 선택. 서버가 반환한 raw/effective TRUE/FALSE/UNKNOWN, 평가/미선택/감시/만료 상태와 실행 경로를 구별한다. 전체 중단은 권한 확인 및 실제 서버 응답 기준으로 표시한다.

## 4. 실시간 데이터와 성능

초기 복구는 [Snapshot + Version](./contracts.md) §8로 확정한다. SSE ready 후 delta 버퍼링 → REST snapshot → aggregate별 버전 대조, 재접속/누락/overflow 시 snapshot 재조회. 장기 replay 저장소는 초기 필수 아님. 권한 변경 시 cache 제거 및 stream 종료.

REST snapshot + SSE delta, TanStack Query cache patch/invalidate; event version 역전/갭 시 재조회. EventSource는 동일 origin HttpOnly session cookie 사용, 브라우저 요청에 장기 API 토큰 노출 금지. 각 화면의 query key에 계좌/모드/버전/기간 포함. UI만 render coalescing 및 requestAnimationFrame, Web Worker에서 큰 차트 데이터 가공 후보, 서버 downsample의 min/max와 확정봉 의미 유지. 숨겨진 탭은 렌더링을 줄이고 수집·매매 엔진은 독립. SSE 끊김·no_update·stale 표시; 1Hz 기록을 1Hz 신규 거래로 오인하지 않는다. 롱숏 최소 5분 집계 및 4종 비율 정의 구분.

UI 성능 목표(실측 전): 100개 카드·200개 노드 합성 시나리오에서 조작 가능성, 초기 로딩·렌더 프레임·메모리 측정. 모바일은 조회/상태 우선, 복잡한 편집은 데스크톱 우선. 키보드 탐색·고대비·색상 독립 접근성 테스트.

## 5. 참조

[React](https://react.dev/) · [Vite](https://vite.dev/) · [React Flow](https://reactflow.dev/) · [Lightweight Charts](https://tradingview.github.io/lightweight-charts/) · [ECharts](https://echarts.apache.org/) · [TanStack Query](https://tanstack.com/query/latest)
