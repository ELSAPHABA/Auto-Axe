# DRAMeXchange DDR5 모듈 가격 지표 수집 명세

> 확인일: 2026-11-24. 지정 공개 홈페이지의 대상 행 및 열 확인 완료. 자동 스크래핑·적재·활용 권한 확인 필요; 실제 HTTP 파서 및 운영 수집기 미구현. 유료 서비스 제외.

## 1. 지정 수집 대상

- 원본 URL: https://www.dramexchange.com/
- 표/섹션: **Module Spot Price**
- 추출 열: **Session Average** (제공자가 계산한 해당 세션의 평균 가격, 자체 재계산하지 않음)

| Item (원문 완전 일치) | series_id | 분석 용도 |
|---|---|---|
| DDR5 UDIMM 16GB 4800/5600 | `DRAM_DDR5_UDIMM_16GB_SESSION_AVG` | 일반 PC용 DDR5 모듈 현물가격 동향 |
| DDR5 RDIMM 32GB 4800/5600 | `DRAM_DDR5_RDIMM_32GB_SESSION_AVG` | 서버용 DDR5 등록형 모듈 현물가격 동향 |

4800/5600은 원본에서 하나의 통합 항목명이다. 속도별 네 개 시계열로 임의 분할하지 않는다. 용량 단위는 모듈 **GB**이며 DRAM 칩의 Gb와 다르다. 일반 `DRAM Spot Price` 섹션의 DDR5 16Gb 칩 가격, DRAM 계약가격, HBM 가격, 소매점 가격, DXI 지수로 대체하지 않는다. 두 상품의 단위·용량·시장 차이가 있으므로 별도 시계열로 유지한다.

## 2. 원본 갱신 주기

[DRAMeXchange Price Information](https://www.dramexchange.com/Intelligence/PriceInformation)은 **Module Spot Price를 주간 갱신**으로 설명한다. 일반 DRAM 칩 현물가격의 일 3회 갱신 정책을 모듈에 적용하지 않는다. 홈페이지에서 모듈 표의 독립적인 `Last Update: ... (GMT+8)` 표시와 해당 두 행을 확인했다. 2026-11-24 조사에서 검색 인덱스에 11월 9일·16일 갱신본 등 서로 다른 캐시가 관측되어 최신 가격을 확정하지 않는다.

- 허용된 경우 기본 조회 스케줄: 일 1회(예: 대만시간 15:00, 한국시간 16:00), 실제 주간 갱신만 신규 관측으로 적재. 이는 프로젝트의 점검 시각이지 제공자 보장 갱신 시각이 아니다.
- `Module Spot Price` 섹션 자체의 Last Update를 소스 시각으로 사용. 다른 섹션의 시각이나 HTTP Date와 혼동 금지.
- `Asia/Taipei` (GMT+8)에서 UTC로 변환하고 `Asia/Seoul` 표시를 지원. UTC 수집 시각은 별도로 저장.
- 같은 원본 갱신시각이면 신규 주간 가격으로 중복 저장하지 않는다. 같은 시각의 정정 값은 revision으로 기록한다. 값은 같아도 원본 시각이 바뀌면 새 발표로 저장한다.
- 일중/초단위 실시간 지표가 아니다. 일별 분석에서는 마지막 공개 관측값과 그 원본 시각을 유지하며 오래된 값임을 표시한다.

## 3. 스크래핑 설계 (권한 승인 후)

목표 수집 방식은 `SCRAPE`: 공개 홈페이지 HTML을 일반 HTTP GET으로 받아 Python requests + BeautifulSoup 또는 pandas 기반으로 파싱한다. 웹 열람 도구에서 대상 텍스트는 확인했으나 raw HTTP/DOM 구조 및 정확한 CSS selector는 실측하지 않았다. 셀 인덱스나 CSS ID를 고정 추정하지 않는다.

1. 사용 권한 확인 및 `robots.txt` 재점검 후 허용된 요청만 수행. HTTP 200 및 정상 HTML 응답 확인.
2. 제목이 정확히 `Module Spot Price`인 섹션과 인접한 Last Update 및 표를 식별한다. `DRAM Spot Price`나 다른 표의 동일한 열 이름은 제외한다.
3. 헤더의 공백·개행을 정규화한 뒤 `Item`, `Session Average`의 열 위치를 이름으로 찾는다. rowspan/colspan 등은 실제 DOM에 맞게 정규화한다.
4. 지정된 두 원문 Item과 정규화 공백 기준으로 정확히 일치하는 행을 각각 1개 확인한다. `Session Average` 텍스트를 Decimal로 파싱한다. `Weekly High/Low`, `Session High/Low`, `Average Change`는 목표 열이 아니다.
5. 양 행의 존재·중복·수치 형식·업데이트 시각·양수 여부를 검증하고 원본 문자열을 보존한다. 행이나 값이 누락되면 0으로 채우지 않는다. `SCHEMA_CHANGED`, `MISSING_VALUE`, `PERMISSION_REQUIRED`, `FETCH_FAILED` 등으로 구분한다. 통화와 가격 단위는 제공자 공식 표기 확인 전 확정하지 않는다.
6. 초기 HTTP 결과에 정상 표가 없다면 허용된 범위의 일반 브라우저 렌더링(Playwright)을 검토한다. 로그인 벽, 유료 멤버십, CAPTCHA, 403/429 등을 우회하지 않고 중단하거나 허용 범위에서 백오프한다. 숨은 API는 역공학하지 않는다.

### 파서 핵심 예시 (DOM 식별 이후, 네트워크 호출 없는 예제)

```python
from decimal import Decimal

ITEMS = {
    "DDR5 UDIMM 16GB 4800/5600": "DRAM_DDR5_UDIMM_16GB_SESSION_AVG",
    "DDR5 RDIMM 32GB 4800/5600": "DRAM_DDR5_RDIMM_32GB_SESSION_AVG",
}

def normalize(value):
    return " ".join(str(value).split())

def extract_module_averages(rows):
    # rows: Module Spot Price 섹션에서 헤더 기반으로 파싱한 dict 목록
    result = {}
    for row in rows:
        label = normalize(row["Item"])
        if label not in ITEMS:
            continue
        key = ITEMS[label]
        if key in result:
            raise ValueError(f"Duplicate item: {label}")
        raw = normalize(row["Session Average"])
        value = Decimal(raw.replace(",", ""))
        if not value.is_finite() or value <= 0:
            raise ValueError(f"Invalid price: {label}")
        result[key] = {"item": label, "raw_value": raw, "value": value}
    if set(result) != set(ITEMS.values()):
        raise ValueError("Target row missing")
    return result
```

이 예시는 구조화된 표 데이터의 필드 추출 로직만 제시한다. 실사이트 요청이나 DOM selector 검증이 완료된 운영 스크래퍼가 아니다.

## 4. 저장·활용

| 필드 | 값/정의 |
|---|---|
| provider | `DRAMeXchange` (TrendForce) |
| collection_method | `SCRAPE` (승인 후), 허용된 수동 입력 시 `MANUAL` |
| series_id | 지정된 두 ID |
| item_name | 원본 Item |
| section | `Module Spot Price` |
| metric | `Session Average` |
| raw_value / value | 원문 문자열 및 Decimal |
| currency / unit | 공식 표기 확인 후 설정. 미확인 시 null + unit_unverified. 임의 USD/모듈 단정 금지 |
| frequency | `WEEKLY` |
| source_updated_at | 섹션 Last Update → UTC |
| observed_at_utc | 실제 수집 시각 |
| source_url | https://www.dramexchange.com/ |
| quality_status / permission_status | 검증 및 권한 상태 |
| revision | 정정 이력 |

중복 키는 `provider + series_id + source_updated_at` (정정 시 revision). 원본 시각이 백테스트 시점 이후인 자료는 사용하지 않는다. 필요 시 전회 대비 가격 변동률을 두 시계열 각각 계산하되, 신규 공개 자료가 있을 때만 갱신하고 원본의 Average Change 필드와 별도 이름으로 관리한다.

## 5. 무료 범위 및 권한

- 홈페이지에 두 행 및 Session Average가 공개 표시되는 것은 확인했다. 공개 열람과 자동 수집/장기 저장/재배포 허용 여부는 별개다.
- [Terms of Use](https://www.dramexchange.com/About/TermsOfUse) 5항 d~h 및 6.1~6.3: 서비스 방해 및 보안 침해 제한, 미래 사건 관련 베팅·예측시장 등 특정 투기 활동에 콘텐츠 이용 금지, 콘텐츠 복제·가공·제3자 유통 등에 사전 서면 동의 요구. Auto-Axe의 분석 목적, 자동 수집·저장·파생지표 활용 범위를 제공자에 확인한다. 출처 표기만으로 허용을 가정하지 않는다.
- [robots.txt](https://www.dramexchange.com/robots.txt)는 이번 웹 조사에서 조회되지 않아 내용 확인 불가. 허용/차단을 단정하지 않는다.
- 상세 [Module Spot Price](https://www.dramexchange.com/Price/Module_Spot) 페이지는 조사에서 로그인 페이지로 이동했다. 공개 홈페이지만 목표로 하며 제한된 상세자료·유료 히스토리 다운로드는 사용하지 않는다.
- 운영 상태: `permission_required`, 기본 자동 실행 비활성. 예시 환경설정 `AUTO_AXE_DRAMEXCHANGE_SCRAPE_AUTHORIZED=0`; 무료이며 목적에 맞는 허가가 확인된 경우에만 활성화한다. 허용되지 않으면 결측 유지, 허용된 범위에서 수동 열람/입력만 검토. 약관 제한은 수동 입력으로 우회하지 않는다.
- 현재 작업 범위는 docs 명세 등록이며, 운영 코드 및 스케줄은 미구현.

## 출처

- [지정 원본 홈페이지](https://www.dramexchange.com/)
- [가격 정보 및 Module 주간 갱신 정책](https://www.dramexchange.com/Intelligence/PriceInformation)
- [FAQ: Session Average 정의 및 히스토리 이용 범위](https://www.dramexchange.com/Service/faqs)
- [Spot Price Notice](https://www.dramexchange.com/Service/Spot_Price_Notice) — 일반 가격 세션·회원 등급별 시각, 모듈 주간 주기와 구분
- [Terms of Use](https://www.dramexchange.com/About/TermsOfUse)
- [전체 지표 목록](./Indicator_Data_Sources.md) · [무료 수집 카탈로그](./Free_Data_Collection.md) · [수집기 설계](./Collector_Design.md)
