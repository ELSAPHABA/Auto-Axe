# 미국 주식 파생상품 트리플·쿼드러플 위칭 캘린더

> 2026-11-27 사용자 변경: 규칙 기반 표준 분기 만기 예상 일정이 기본. 공식 거래일 캘린더로 휴장일 자동 보정하며, 실제 계약별 만기 근거는 별도 검수한다. 직접 OCC/CME/Cboe 자동 취득은 기본 예상 일정의 선행 조건이 아니다.

## 0. 기본 예상 일정 (구현)

- 3·6·9·12월 셋째 금요일을 명목 후보로 생성하고, 검수된 NYSE Arca 주식시장 정규 거래일 캘린더에서 직전 열린 세션까지 역순 보정한다. 연속 휴장도 처리하며 조기 폐장은 열린 거래일이다. 예: 2027-06-18 Juneteenth 대체 휴장 → 2027-06-17.
- 달력일 DTE 및 미국 주식시장 거래일 DTE는 America/New_York 날짜 기준이다. 목표 당일 0, 오늘 제외/목표일 포함. 지난 만기의 DTE는 null. 확인된 거래일 범위 밖이나 누락된 구간에는 값을 추정하지 않는다. 현재 NYSE Arca 캘린더는 2028년까지이며, 이후 기존 검수 manifest로 확장한다.
- `GET /api/v1/dashboard/expiry-calendar`는 기본적으로 휴장일 보정 후 다음 예상 만기를 자동 선택한다. `candidate_date=YYYY-MM-DD`로 명목 분기 후보를 지정할 수도 있다. 별도 `projection`에 명목/예상일, 두 DTE, 달력/규칙 버전 반환. 60초 프런트 조회로 갱신.
- 주식시장 거래일 DTE는 실제 선물/옵션 상품별 거래 세션 DTE가 아니다. 실제 계약의 휴장 예외, 정산/최종 거래, 활성 계약, 세 마녀/네 마녀 성립은 아래 공식 검수 경로에만 의존한다. 추정값은 기존 확정 근거 테이블이나 trading gate에 승격하지 않는다.

## 1. 구분 및 이벤트 정의

| 상품군 (product_family) | Triple Witching (세 마녀의 날) | Quadruple Witching (네 마녀의 날) |
|---|---|---|
| 개별주식 옵션 (`EQUITY_OPTION`) | 포함 | 포함 |
| 주가지수 옵션 (`INDEX_OPTION`) | 포함 | 포함 |
| 주가지수 선물 (`INDEX_FUTURE`) | 포함 | 포함 |
| 개별주식 선물 (`SINGLE_STOCK_FUTURE`) | 미포함 | 포함 |

미국 주식시장 기준 3·6·9·12월 셋째 금요일이 통상적인 분기 동시 만기 후보일이다. 상품별 휴장·만기·정산 규칙이 다르므로 공식 일정으로 확인한다. 월말 분기 옵션(EOQ)이나 매주/매일 옵션 만기, 개별 선물 롤오버일은 분기 동시 만기와 동일한 이벤트로 간주하지 않는다.

**현행 시장 구조 (중요):** OneChicago의 증권거래소 등록 철회는 2020-09-30 효력 발생. 이후 미국 개별주식 선물 시장의 공백 때문에 분기 동시 만기를 트리플 위칭이라고 부르던 기간이 있었으나, CME가 2026-07-27 개별주식 선물을 재도입했다. CME의 현재 상품 페이지에서 55개 미국 주식 대상 상품 및 분기별 계약을 확인할 수 있다. 통상 최종거래는 만기월 셋째 금요일 16:00 ET, 현금결제는 기초주식 공식 종가 기준이다. 따라서 **2026년 하반기 이후에도 실제 4개 상품군의 동시 만기 가능**; '2020년 이후 쿼드러플 위칭 없음'이라는 고정 규칙 금지. 상장·폐지 및 실제 계약 일정을 확인해 판정한다.

## 2. 무료 공식 출처

| 상품군 | 우선 출처 | 확인 대상 |
|---|---|---|
| 주식/ETF 옵션 | [OCC/OIC 만기 달력](https://www.optionseducation.org/referencelibrary/expiration-calendar), [Cboe 옵션 거래시간 및 휴장](https://www.cboe.com/about/hours/us-options) | 표준 월간 옵션 만기, 휴장 및 계약별 예외 |
| 지수 옵션 | OCC/OIC, Cboe 상품 사양 및 [정산값](https://www.cboe.com/index_settlement_values) | 지수별 만기·AM/PM 정산 |
| 주가지수 선물 | [CME 주가지수 롤·만기일](https://www.cmegroup.com/trading/equity-index/rolldates.html), [CME 최종정산 절차](https://www.cmegroup.com/trading/equity-index/settlement.html) | NQ/ES 등 실제 계약 만기 (롤 날짜와 구분) |
| 개별주식 선물 | [CME Single Stock futures 상품 및 계약 명세](https://www.cmegroup.com/markets/equities/single-stock-futures), [CME SSF FAQ](https://www.cmegroup.com/articles/faqs/faq-single-stock-futures.html), [CME 만기 캘린더](https://www.cmegroup.com/tools-information/calendars/expiration-calendar.html) | 실제 상장된 분기 계약, 마지막 거래일, 정산일, 휴장 조정 |

시장 구조의 출처: [SEC OneChicago 등록 철회 공지](https://www.sec.gov/rules-regulations/2020/12/onechicago-llcs-notice-withdrawal-registration-national-securities-exchange-solely-purposes-trading), [CME 2026-06-30 출시 발표](https://www.cmegroup.com/media-room/press-releases/2026/6/30/cme_group_to_launchsinglestockfuturesonjuly27.html), [CME 현행 상품 페이지](https://www.cmegroup.com/markets/equities/single-stock-futures).

공식 공개 일정은 무료 열람 범위에서 이용. 자동 파싱은 각 사이트의 약관/허용 범위 확인 후 사용하고, 불가하면 공식 자료를 수동 입력한다. **CME 실시간 거래 데이터 라이선스 및 유료 피드 불필요**: 일정 이벤트 수집이 목적이다. yfinance 옵션 체인 만기 목록은 개별 종목 보조 검증용 후보이며, 시장 전체 위칭 유형의 단독 확정 출처가 아니다. Binance/MEXC 영구선물 및 암호화폐 옵션은 미국 주식 위칭 판정에서 제외한다.

## 3. 이벤트 분류 파이프라인

1. 매년 3·6·9·12월 셋째 금요일 후보일 생성. 휴장 여부와 각 계약의 실제 만기일은 공식 캘린더·상품 사양·정정 공지로 별도 확인한다.
2. 미국 동부시간(`America/New_York`)의 실제 만기 세션(`effective_session_date`)을 상품군별로 정규화하고, 명목 만기일/최종 거래일/처리일/정산 시각을 각각 보존한다. 동일 세션에 속해도 AM과 PM 정산이 서로 다를 수 있다.
3. 분기 표준 만기 대상의 실제 활성 계약 존재 및 같은 세션 만기 여부를 확인하고, 상품군별 `YES/NO/UNKNOWN`으로 기록한다. 데이터 미수집은 `NO`가 아니다. 개별주식 옵션과 ETF 옵션을 별개의 '마녀'로 세지 않으며, 지수선물 옵션을 별도로 더하지 않는다.
4. 기본 3개 상품군 모두 `YES`이고 개별주식 선물 `NO`이면 `TRIPLE_WITCHING`; 네 상품군 모두 `YES`이면 `QUADRUPLE_WITCHING`. 미확인 상품군 때문에 분류가 확정되지 않으면 `PENDING_VERIFICATION`, 3개 미만이 확정된 경우 `NONE`(단, 미확인으로 결과가 달라질 수 있으면 보류). 4종 동시 만기는 **한 건의 QUADRUPLE 이벤트**로 기록하며 TRIPLE 이벤트를 중복 생성하지 않는다.
5. 시장 보도에서 관행적으로 같은 분기 만기일을 triple/quad라고 부를 수 있으므로 원문 명칭은 `reported_label`에 보존하되 공식 계약 근거에 따른 `event_type`과 분리한다.
6. 미국 휴장/예외 변경 시 기존 레코드 수정 이력을 남긴다. 주간 정기 갱신 및 변경 공지 확인; 해당 주에는 일별 확인 권장.

### 판정 예시 (구현 참고용, 실제 만기일 확정 목록 아님)

```python
from datetime import date, timedelta

FAMILIES = (
    "EQUITY_OPTION", "INDEX_OPTION", "INDEX_FUTURE",
    "SINGLE_STOCK_FUTURE",
)

def third_friday(year, month):
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)

def classify_witching(status):
    # status: each family -> True (confirmed), False (confirmed absent), None
    core = [status.get(key) for key in FAMILIES[:3]]
    ssf = status.get(FAMILIES[3])
    if any(v is False for v in core):
        return "NONE"
    if any(v is None for v in core) or ssf is None:
        return "PENDING_VERIFICATION"
    return "QUADRUPLE_WITCHING" if ssf is True else "TRIPLE_WITCHING"

assert classify_witching(dict(zip(FAMILIES, [True, True, True, False]))) == "TRIPLE_WITCHING"
assert classify_witching(dict(zip(FAMILIES, [True, True, True, True]))) == "QUADRUPLE_WITCHING"
assert classify_witching(dict(zip(FAMILIES, [True, True, True, None]))) == "PENDING_VERIFICATION"
```

셋째 금요일 함수는 후보 날짜 생성용이다. 휴장 전일로 무조건 이동시키지 않고 공식 계약 명세로 실제 날짜를 확정한다. 예: 2026-06-19 Juneteenth의 명목 만기·처리일 차이는 [OCC 공지 56694](https://infomemo.theocc.com/infomemos?number=56694) 참조.

## 4. 저장 필드 및 분석 피처

기존 `event_calendar` 기반 계약별 원자료에서 파생 위칭 이벤트를 생성한다.

| 필드 | 정의 |
|---|---|
| `market` | `US_EQUITY` |
| `event_type` | `TRIPLE_WITCHING` / `QUADRUPLE_WITCHING` / `PENDING_VERIFICATION` / `NONE` |
| `candidate_date` | 분기 셋째 금요일 후보 |
| `effective_session_date` | 검증된 미국 동부시간 세션 날짜 |
| `family_status` | 4개 상품군 YES/NO/UNKNOWN |
| `contract_refs` | 실제 계약·상품군 및 원본 이벤트 식별자 목록 |
| `source_urls`, `verified_at_utc`, `revision` | 원본 출처, 확인 시각, 변경 이력 |
| `expiry_date`, `last_trade_at`, `processing_at`, `settlement_at`, `am_pm` | 계약별 원본 레코드에 보존; 위칭 이벤트에 단일 정산 시각을 강제하지 않음 |
| `reported_label` | 외부 관행적 명칭(선택) |

별도 분석 지표:

- `IS_TRIPLE_WITCHING_DAY`, `IS_QUADRUPLE_WITCHING_DAY`: 상호 배타적 0/1. 미확인 분류는 null.
- `IS_WITCHING_DAY`: 확정된 두 유형 공통 플래그.
- `DTE_TRIPLE_WITCHING`, `DTE_QUADRUPLE_WITCHING`: 다음 **각 유형의 확인된 이벤트**까지 달력일 수(ET 기준). 없으면 null; 예정 후보는 별도 표시.
- `TRADING_DAYS_TO_WITCHING`: 미국 거래소 세션 달력으로 계산하는 별도 거래일 수. 이벤트 당일 0.
- 과거 백테스트에서는 당시 확인 가능했던 캘린더 버전만 사용하고, 거래량/변동성 변화가 위칭 자체 때문에 항상 발생한다고 가정하지 않는다.

현재 상태: 기본 분기 예상 일정/휴장일 보정/DTE/API/UI 및 기존 공식 계약 검수 저장·조회 경로 구현. 실제 계약 전수 검증 및 운영 공급자 연결은 별도. [Session 14](../../.ai-context/phases/phase-02/2026-11-27-14.md) 참조.
