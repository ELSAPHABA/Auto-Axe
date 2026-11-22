# 무료 시장지표 데이터 소스 카탈로그

> 2026-11-22 · Auto-Axe 공식 수집 우선순위: **무료 API/WebSocket → 허용된 HTML·RSS·ICS 다운로드/스크래핑 → 수동**. 기존 유료 공급원 조사 내용은 폐기되었다.

**상세 항목별 공식 링크·제약·수집 빈도**는 [Free_Data_Collection.md](./Free_Data_Collection.md)가 최신 기준이다. 실행법은 [Realtime_Quickstart.md](./Realtime_Quickstart.md), 수동 항목은 [Manual_Collection.md](./Manual_Collection.md) 참조.

| 항목 | 무료 자동화 우선 | 무료 자동화가 부족할 경우 | 최신성 |
|---|---|---|---|
| CNN 공포·탐욕 | 공식 무료 사용권이 확인된 API 없음 | CNN 원본 수동 입력 | 스냅샷 |
| 기업 가이던스 | SEC EDGAR 제출·Atom, 기업 IR RSS | 허용된 기업 IR HTML → 원문 수동 검수 | 신규 공개 이벤트 |
| 금 | gold-api.com `/price/XAU` | 수동 | 준실시간 캐시 |
| WTI/Brent | EIA 무료 키 일별 현물 PET.RWTC.D/PET.RBRTE.D | 일중 선물값은 수동, 상품 종류 분리 | 일별 |
| Dubai | World Bank Pink Sheet 월간 자료 | 공개 평가자료 수동 | 월별 |
| VIX | Cboe `VIX_History.csv` | 장중 VIX 수동 | EOD |
| 미국 국채 | Treasury Par Yield XML/CSV | 장중 현물수익률 수동 | 일별 |
| 피자지수 | 공개 JSON endpoint(권한 확인 필요) | PizzINT 수동 관찰 | 수동 |
| 경제지표 발표 일정 | BLS ICS, Fed 일정, 공식 BEA/Census 페이지 | 허용 HTML → 수동 | 이벤트 |
| 경제지표 실제값 | BLS v2, BEA API 및 공식 발표문 | HTML → 수동 | 이벤트 |
| 파생상품 만기 | OCC/OIC, CME·Cboe 공개 달력 | 예외 수동 검증 | 예정/수정 |
| 미국 금리 | Fed 결정 RSS + 공식 발표, 공개 시계열 | 수동 검증 | 결정 이벤트 |
| 일본 금리 | BOJ RSS + 통계 API | 정책 성명 수동 검증 | 이벤트/일별 |
| 영국 금리 | BoE 공식 Bank Rate 공개자료 | 정책 성명 수동 검증 | 이벤트/일별 |
| 유로존 금리 | ECB RSS + SDMX DFR API | 성명 수동 검증 | 이벤트/일별 |
| 비트코인 | Coinbase BTC-USD/Binance BTCUSDT 무료 WS | 장애 시 수동 | 체결 스트림 |

무료라고 해서 반드시 실시간이 아니다. **데이터 관측시점과 획득시점을 분리**하고 값의 이용약관을 확인한다. Yahoo 등의 비문서화 quote URL을 약관 확인 없이 자동 수집기로 등록하지 않는다.


## 2026-11-22 사용자 지정 소스 및 추가 시험

- **피자지수:** [PizzINT](https://www.pizzint.watch/) (기존 pentagon.pizza 대체). 공개 JSON URL /api/dashboard-data HTTP200 확인. 단 robots `Disallow:/api/` 및 Terms의 API 외 스크래핑 금지로 허가 확인 전 수동.
- **공포·탐욕:** [CNN International](https://edition.cnn.com/markets/fear-and-greed) (기존 www.cnn.com 원본 대체). CNN Terms에 따라 자동 스크래핑 승인 전 수동.
- **yfinance:** VIX `^VIX`, 국채 지표 `^TNX`, WTI 선물 `CL=F`, Brent 선물 `BZ=F`의 일봉·1분봉 실제 조회 검증. 실시간 지연 없음 미보증, Dubai유 일별 실제 spot 심볼 미확인. [상세](./YFinance_Data_Validation.md).
