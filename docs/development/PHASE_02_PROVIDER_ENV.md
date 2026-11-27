# Phase 2 공급자 환경변수 설정

실제 수집 검증에 필요한 무료 등록 정보 (Session 15 기준). 운영 DB/인증/네트워크 설정은 [Compose 안내](../../infra/compose/README.md) 참조.

| 환경변수 | 발급·설정 | 대상 | 미설정 시 |
|---|---|---|---|
| `AUTOAXE_BEA_API_KEY` | [BEA 무료 등록](https://apps.bea.gov/API/signup/) | GDP T10101, PCE T20807 | 실제값 검증 보류 |
| `AUTOAXE_CENSUS_API_KEY` | [Census 무료 등록](https://api.census.gov/data/key_signup.html) | MPCSM 소매판매 | 실제값 검증 보류 |
| `AUTOAXE_FRED_API_KEY` | [FRED API 키](https://fred.stlouisfed.org/docs/api/api_key.html) | DFEDTARL, DFEDTARU | 목표금리 범위 검증 보류 |
| `AUTOAXE_SEC_CONTACT` | [SEC API 안내](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), 실제 이름/조직 및 연락 이메일 | 8-K, Exhibit 99.1, 실적 가이던스 후보 | SEC 요청 보류 |

SEC는 API 키가 아니다. BEA/Census 발표 일정과 BLS v1은 위 키 없이 검증 완료. 네 변수는 해당 수집기를 사용할 때만 필요하다.

## PowerShell 설정 (현재 세션)

```powershell
$env:AUTOAXE_BEA_API_KEY = '<BEA key>'
$env:AUTOAXE_CENSUS_API_KEY = '<Census key>'
$env:AUTOAXE_FRED_API_KEY = '<FRED key>'
$env:AUTOAXE_SEC_CONTACT = 'Auto-Axe Research real-contact@example.com'
```

위 값은 예시이며 실제 발급 정보로 대체한다. 실제 키를 셸 기록, 채팅, Git, 로그에 남기지 않도록 로컬 비밀 저장소 또는 안전한 입력 경로로 주입한다. 기존 예제 `docs/examples/.env.example`은 PoC용으로 운영 변수명과 다르다. Compose `phase2-collectors.yaml`은 위 AUTOAXE_ 변수를 전달한다.

## 값 노출 없이 설정 여부 확인

```powershell
foreach ($name in @('AUTOAXE_BEA_API_KEY','AUTOAXE_CENSUS_API_KEY','AUTOAXE_FRED_API_KEY','AUTOAXE_SEC_CONTACT')) {
    $configured = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))
    Write-Output "$name configured=$configured"
}
```

설정 여부는 유효성이나 공급자 권한을 보장하지 않는다. 설정 후 기존 수집기에서 실제 응답과 임시 DB 저장을 검증한다. SEC 문서 수집에는 대상 CIK도 명시해야 하며, 추출 후보는 별도 검수한다. 이번 문서 작성에서는 실제 키 등록, 환경변수 변경, 외부 요청 및 운영 활성화를 수행하지 않는다.
