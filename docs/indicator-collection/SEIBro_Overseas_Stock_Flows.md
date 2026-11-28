# SEIBro 해외주식 매수·매도 결제 통계 수집 명세

> 상태(2026-11-28 Session24): Scrapling Selector + 정상 Chromium 격리 수집, 미국 15개 scope 일괄 자동 검증·영속 일일 스케줄 및 조건부 거래 권한 구현. 실제 TOP50 조회/자동 이용 권한·운영 egress 미확인, 운영 미배포. 무료 정책 적용. 최신 계약은 §8이며 이전 설계와 검수 이력은 역사적 기록이다.

공식 [국제거래외화증권예탁결제정보](https://www.data.go.kr/data/15043445/openapi.do)는 무료 REST(JSON/XML), 공공누리 2유형, 개발/운영 자동승인 및 인증키 신청 경로를 제공한다. 제공 설명은 국가/시장/증권구분 결제 통계이며 지정 TOP50의 ISIN·순위·기간별 정확한 종목 결제금액 제공은 확인되지 않았다. 따라서 별도 통계를 TOP50 원장에 대체 저장하지 않는다. 한국예탁결제원 [공유자원포털](https://api.seibro.or.kr/pubc/pubr/cmm/CMPubrHome/viewCMPubrHome.do)에서 정확한 API 계약을 확인하거나 portal@ksd.or.kr에 문의한다. 상세 검증은 [Session 18](../../.ai-context/phases/phase-02/2026-11-28-18.md).

## 1. 원본 페이지와 확인한 범위

- **제공처:** 한국예탁결제원 증권정보포털 **SEIBro**
- **사용자 지정 원본:** [종목별내역(주식TOP50)](https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921)
- **화면 정의:** `/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml` (2026-11-23 HTTP 200, UTF-8 XML로 직접 확인)
- **메뉴 제목:** `종목별내역(주식TOP50)`
- **수집 목적:** 국내 투자자의 해외주식 매수·매도 결제 동향을 참고하는 **서학개미 수급 지표**. 그러나 **'개인투자자만'의 거래라고 단정하지 않는다**. 집계 대상은 SEIBro가 포착한 외화증권 예탁·결제 내역이며 국내 개인투자자 전체의 원시 주문·체결 데이터와 다른 통계다.
- **범위 주의:** 해당 화면은 **주식 TOP50 랭킹**이다. **전체 해외주식 시장의 전 종목 합계/국내 투자자 총 매수·매도액**이라고 이름 붙이지 않는다. 50위 밖 종목은 포함되지 않을 수 있다.

## 2. 원본 화면에서 직접 확인한 조회 옵션

| 기준 | 실제 화면 값 | Auto-Axe 기본/비고 |
|---|---|---|
| 현황구분 | `결제금액` (값 `2`), `보관금액` (값 `1`) | **결제금액**. 보관금액은 보유 잔고이므로 매매 수급 지표에서 제외 |
| 세부구분 | `매수결제` (`1`), `매도결제` (`2`), `매수+매도결제` (`3`), `순매수결제` (`4`) | 네 유형 모두 별도 조회·순위를 기록. 랭킹 기준이 다르므로 통합 시 유의 |
| 조회기간 | `1주` (`1`), `1개월` (`2`), `3개월` (`3`), `6개월` (`4`), `1년` (`5`) | 각 기간을 분리 저장. **일별 개별 결제액을 제공한다고 단정하지 않음** |
| 국가 | `전체` (`ALL`), `미국` (`US`), `홍콩` (`HK`), `중국` (`CN`), `일본` (`JP`), `베트남` (`VN`) | **미국 `US` 우선**, 필요하면 전체/타국가 추가 |
| 금액 단위 | 화면 표기 `단위 : USD` | USD, 환율 변환으로 만든 KRW 원본값으로 오인하지 않음 |
| 조회기준일 | 화면의 조회기준일 선택 | 결제 기준일을 **원본 메타데이터**로 저장, 수신시각과 분리 |

## 3. 결제금액 화면의 실제 테이블 컬럼

아래 필드명은 직접 다운로드한 **WebSquare 화면 XML의 `grid2` 컬럼 정의**에서 확인했다. 백엔드 실제 반환 스키마/숫자 값까지 테스트한 것은 아니다.

| 화면 컬럼 | XML 필드 | 권장 정규화 키 |
|---|---|---|
| 순위 | `RNUM` | `rank` |
| 국가 | `NATION_NM` | `country_name` |
| 종목코드 | `ISIN` | `isin` — 거래소 티커라고 간주하지 않음 |
| 종목명 | `KOR_SECN_NM` | `security_name` |
| 매수결제 | `SUM_FRSEC_BUY_AMT` | `buy_settlement_usd` |
| 매도결제 | `SUM_FRSEC_SELL_AMT` | `sell_settlement_usd` |
| 매수+매도결제 | `SUM_FRSEC_TOT_AMT` | `gross_settlement_usd` |
| 순매수결제 | `SUM_FRSEC_NET_BUY_AMT` | `net_buy_settlement_usd` |

**해석:** 순매수 결제금액은 일반적으로 매수 결제금액 − 매도 결제금액이다. 원본 `SUM_FRSEC_NET_BUY_AMT` 값을 우선 보존하고, 같은 종목·기간·국가의 매수/매도 값이 모두 있는 경우에만 계산 검증한다. **랭킹 외 결측 종목을 0원으로 보정하지 않는다.**

**결제와 체결의 차이:** SEIBro 화면 안내는 `결제금액`을 *결제금액이 있는 매수·매도 거래*의 금액으로 설명하며 인수·인도·계좌대체 건은 제외한다고 표기한다. 한국시간 기준 결제처리·권리처리 완료일을 조회기준일로 사용한다. 따라서 체결 당일 실시간 거래량/계좌별 수익금으로 해석하지 않는다.

## 4. 스크래핑 설계 — 구현 전 검증 사항

[Scrapling 수집 표준](../tech-stack/data-collection.md) 및 [보안 설계](../tech-stack/security.md)를 따른다. UI 동작·셀렉터·권한 검증 전 자동화 비활성, 허용 수동 fallback.

- **예정 방식: 공개 화면 스크래핑**. 실제 HTML 엔트리 `/websquare/control.jsp`는 HTTP 200으로 약 1KB **WebSquare 로더**만 반환하며 테이블 데이터는 정적 HTML에 없다. 화면 정의 XML `BIP_CNTS10013V.xml`은 2026-11-23 확인했다.
- 웹 화면을 정상적으로 렌더링하는 **Scrapling 기반 정상 브라우저 렌더링(승인 및 격리 검증 후)**로 현황구분→세부구분→조회기간/기준일→국가→조회 순서에 따라 화면 표시 테이블을 읽는 방법을 우선 설계한다. **셀렉터·전송 요청 본문·쿠키 정책은 브라우저 실제 세션에서 검증한 뒤 확정**하며, 지금은 미검증이다.
- 화면 XML에는 `submission_getImptFrcurStkSetlAmtList`라는 결제금액 관련 전송 정의가 보인다.
- `https://seibro.or.kr/robots.txt`는 확인 당시 **HTTP 200, 길이 0바이트**였다.
- 갱신 주기는 페이지 제공 시점 및 결제 데이터 반영 지연을 관측한 뒤 결정한다. **실시간/분봉 지표가 아니다.** 일정 간격으로 페이지를 재조회한다고 새 결제값이 생성되는 것은 아니다.

## 5. 수집 레코드 권장 스키마

```json
{
  "series_id": "SEIBRO_OVS_STOCK_TOP50_SETTLEMENT",
  "provider": "KSD_SEIBRO",
  "source_url": "https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921",
  "status": "planned_scrape_permission_pending",
  "security_type": "overseas_stock",
  "country_code": "US",
  "rank_basis": "net_buy_settlement",
  "period_code": "1",
  "period_start": null,
  "period_end": null,
  "as_of_date_kst": null,
  "isin": null,
  "security_name": null,
  "rank": null,
  "buy_settlement_usd": null,
  "sell_settlement_usd": null,
  "gross_settlement_usd": null,
  "net_buy_settlement_usd": null,
  "currency": "USD",
  "retrieved_at_utc": null,
  "source_data_delay": "not_verified"
}
```

- 위 JSON의 `null`은 **실제 결제값이나 데이터가 아니라 데이터 구조 예시**다.
- `series_id`는 Auto-Axe 자체 내부 정의이며 SEIBro 공식 API 명칭이 아니다.
- `country_code + period_start + period_end + rank_basis + isin` 등을 포함한 **복합키**와 최초 관측 시각을 사용한다. 조회기간이 겹치면 합계를 합산하지 않는다.
- 조회 결과의 TOP50 매수/매도액 합계는 `top50_coverage=true`를 명시한다. **전체 시장 순매수 총액으로 표현하지 않는다.**

## 6. Auto-Axe 통합 상태

| 항목 | 상태 |
|---|---|
| 지표 수집 카탈로그 등재 | 완료 |
| 원본 페이지·조회 옵션·테이블 XML 필드 검증 | 완료 |
| 공식 자동 수집 허용 여부 | **확인 필요** |
| 실제 WebSquare 결과 데이터·HTML 셀렉터 검증 | **미완료** |
| Python 스크래퍼 작성·운영 | Scrapling Selector + 정상 Chromium 15-scope 일괄 및 일일 영속 스케줄 구현, 오프라인 Chromium/DB 검증; 실결과 및 운영 미검증 |
| 임시 수집 | SEIBro 화면에서 수동 기록 |

관련 문서: [지표별 출처](./Indicator_Data_Sources.md) · [무료 수집 카탈로그](./Free_Data_Collection.md) · [수동 기록 레지스트리](./Manual_Collection.md).

## 7. 이전 구현 점검 — Session 23 (역사적 기록)

- `seibro_browser.py`는 정상 Chromium/Playwright로 결제금액, 국가·기간·정렬 UI를 선택하고 화면 날짜·USD·표시된 50개 행을 검증한다. 숨은 API 호출 없음. 1/2는 buy_only/sell_only, 3/4는 표시값과 산술 검증 후 누락된 net/gross를 파생값으로 기록한다.
- `seibro_review_cli capture-browser` 기본 US / 1주 / 순매수(4); 86400초 source-wide 예약으로 모든 국가·기간·정렬을 각각 매일 자동 수집하지 않는다. daemon 없음. 동일 초기 결과와 일치하거나 50행 미만이면 실패할 수 있다.
- `ops.seibro_captures`, `ops.seibro_reviews`, `ops.seibro_promotions`에서 독립 검수 후 `indicators.seibro_top50_snapshots` 및 `indicators.seibro_top50_rows`에 append-only 저장. `/api/v1/dashboard/authorized/seibro`는 권한/시점별 하나의 전체 snapshot만 조회한다. DB 및 API는 automated_trading_allowed=false를 강제한다. 이번 사용자 요청은 Toss에 한정되므로 SEIBro 거래 제한은 변경하지 않는다.
- Session 13 초기 DOM/XML 확인 및 로컬 Chromium fixture/PG17 테스트 기록, Session 18 관련 31 passed 기록만 존재한다. 실사이트 TOP50 조회 결과, 실제 운영 자동 수집 권한 및 격리 egress는 미검증. 이번에는 외부 사이트 요청 없이 코드/명세를 확인했다.

## 8. Session 24 사용자 확정 개선 계약

미국(US), 조회 기간 1주/1개월/3개월/6개월/1년, 매수(1)/매도(2)/순매수(4)의 15개 조합을 하루 한 번 영속 예약 및 자동 수집한다. Scrapling 기반 정상 브라우저 표시값 추출, 안전한 요청 경계, 자동 구조/수치/순위/기간 검증, 권한 버전 및 중복 방지를 유지한다. 조회 대상의 순위 집합을 섞지 않으며 관측하지 않은 금액은 null, 파생값은 provenance로 구분한다. 공급자 승인과 독립적으로 사용자 제품 기능상 모든 검증된 SEIBro 수급 필드의 자동매매 판단 활용을 허용한다. 실제 운영 사용은 승인된 fetch/storage/trading grant 및 adapter 검증 근거, 최신 허용된 데이터와 Workflow 실행 계약을 충족해야 한다. 과거 레코드의 권한 및 출처는 소급 변경하지 않는다. 미검증 수집·결측·권한 없음은 거래 판단 UNKNOWN이며 실제 주문 승인과 별개이다.

- 브라우저는 Playwright의 일반 Chromium sandbox를 유지하고 화면에 표시된 셀만 detached HTML로 투영하여 Scrapling 0.5.1 Selector로 파싱한다. 원본 페이지 HTML, 숨은 셀, 비공개 요청 응답/JS 상태는 저장·추출하지 않는다. 동일한 결과는 조회 후 기존 행 전체 교체와 명시적인 aria-busy 완료 증거가 있을 때만 수용한다. 실사이트 해당 동작은 미확인이다.
- 0024 migration: `ops.seibro_adapter_grants`, `ops.seibro_daily_batches`, `ops.seibro_validated_promotions`. 현재 source version과 독립 adapter 승인 이후 15개 검증 결과를 하나의 트랜잭션으로 승격하고 `quality=adapter_validated`로 보존한다. 별도 수동 검수 레코드를 조작하지 않는다. 기존 단발 수동 경로는 호환 유지하며 새 독립 검수 결과도 현재 trading grant에 따라 이용 가능하다.
- `capture-daily` 단발, `run-daily` 지속 실행. 300초 DB 예약 확인, 86400초 source-wide 예약, 480초 batch launcher 제한, 브라우저 최대 400 요청/48 MiB. 일회 조회 실패 또는 일부 scope 누락 시 전체 배치 미승격, 당일 즉시 재시도 없음. 원본 결제 기준일/최초 수신·사용 가능 시각은 그대로 보존하고 동일 내용 재검증 시 `last_validated_at`만 별도 receipt에서 조회한다.
- 현재 API의 거래 허용 bool은 권한 및 검증 상태 표시이며 실제 주문 가능 여부가 아니다. 후속 Workflow는 해당 조건에 필요한 결제 기준일/수집 receipt freshness, 권한 버전, 누락 여부를 함께 검사한다. 기간 중첩 합산과 TOP50 밖 종목의 0 보간은 금지한다.
- 공급자 공식 2020-07-22 회원약관 제8/10조의 영리/제3자 이용 제한, 제14조의 투자 손실 및 적시성/정확성 면책을 재확인했다. 제14조를 자동매매 자체의 명시적 금지로 오해하지 않으나, 비회원 자동 수집 및 사용 허가를 확정하는 근거도 아니다. 공개 자료를 검토했을 뿐 실제 TOP50 데이터 요청/운영 grant는 수행하지 않았다.
