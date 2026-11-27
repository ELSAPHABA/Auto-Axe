# Auto-Axe 사용 안내 — API 키 및 환경변수 설정

Auto-Axe 설치 후 미국 경제지표 및 기업 공시 수집 기능을 사용하기 위한 안내입니다. 아래 등록은 무료이며, 필요한 기능에 해당하는 키만 발급받으면 됩니다.

## 1. 준비할 항목

| 환경변수 | 수집 대상 | 준비 사항 |
|---|---|---|
| `AUTOAXE_BEA_API_KEY` | GDP, PCE 물가지수 | 무료 API 키 |
| `AUTOAXE_CENSUS_API_KEY` | 소매판매액 | 무료 API 키 |
| `AUTOAXE_FRED_API_KEY` | 미국 기준금리 목표 범위 | 무료 API 키 |
| `AUTOAXE_SEC_CONTACT` | 기업 실적 공시·가이던스 | 실제 이름 또는 조직과 이메일 |

BEA·Census 발표 일정과 BLS v1은 위 키 없이 수집할 수 있습니다. DB 및 네트워크 등 공통 설치 설정은 [배포 안내](../../infra/compose/README.md)를 참고하세요.

## 2. BEA API 키 발급

1. [BEA API 등록 페이지](https://apps.bea.gov/API/signup/)에 접속합니다.
2. 이름 또는 소속, 실제 이메일 주소를 입력합니다. 일회용 이메일은 사용할 수 없습니다.
3. 이용 조건에 동의하고 제출합니다.
4. 수신한 이메일에서 36자 UserID와 활성화 링크를 확인합니다.
5. 링크를 열고 필요한 reCAPTCHA 확인 및 Activate 절차를 완료합니다.
6. UserID를 `AUTOAXE_BEA_API_KEY`에 설정합니다.

공식 자료: [사용자 안내서](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf), [활성화 페이지](https://apps.bea.gov/api/signup/activate.html).

## 3. Census API 키 발급

1. [Census API 키 신청 페이지](https://api.census.gov/data/key_signup.html)에 접속합니다.
2. Organization Name에 실제 소속 또는 개인 연구 용도를 입력합니다.
3. Email Address에 수신 가능한 이메일을 입력합니다. 공식 안내는 .com, .net, .org, .gov, .edu로 끝나는 주소를 요구합니다.
4. 이용 조건에 동의하고 신청합니다.
5. 수신한 이메일의 활성화 링크를 열어 등록을 완료합니다.
6. 이메일에 포함된 키를 `AUTOAXE_CENSUS_API_KEY`에 설정합니다.

공식 자료: [키 발급 안내](https://www.census.gov/data/developers/guidance/api-user-guide.API_Key.html).

## 4. FRED API 키 발급

1. [FRED 계정 등록 안내](https://fred.stlouisfed.org/help/account/fred-account-features/register)를 열고 로그인 화면으로 이동합니다.
2. Create New Account를 선택하고 이메일과 비밀번호로 무료 계정을 생성합니다. 기존 계정이 있다면 로그인합니다.
3. [API Key 안내](https://fred.stlouisfed.org/docs/api/api_key.html)의 Request or view your API keys 링크를 엽니다.
4. 새 키를 신청하고 사용 목적을 요구하는 경우 실제 개인·비영리 연구 목적을 기재합니다.
5. 발급된 32자 영문 소문자·숫자 키를 `AUTOAXE_FRED_API_KEY`에 설정합니다. 사용자마다 자신의 키를 사용합니다.

[FRED API 이용 조건](https://fred.stlouisfed.org/docs/api/terms_of_use.html)의 애플리케이션 고지 요구 등도 준수해야 합니다. 운영자는 해당 고지 및 다른 이용 조건 충족 여부를 확인한 후 활성화하세요.

## 5. SEC EDGAR 연락처 설정

가입이나 키 발급은 필요하지 않습니다. 실제 이름 또는 조직과 연락 이메일을 공백으로 구분하여 `AUTOAXE_SEC_CONTACT`에 설정합니다. 예: `Auto-Axe Research contact@example.com` (예시 이메일은 실제 주소로 교체).

수집 대상 기업의 CIK도 실행 설정에 명시해야 합니다. 공시 추출 후보는 검수 후 사용합니다.

공식 자료: [SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC 개발자 리소스](https://www.sec.gov/about/developer-resources).

## 6. 환경변수 설정

### Windows PowerShell

Auto-Axe를 실행할 PowerShell에서 다음 명령을 사용합니다. 키 입력은 가려지고 명령에 실제 키를 적을 필요가 없습니다.

```powershell
foreach ($name in @('AUTOAXE_BEA_API_KEY','AUTOAXE_CENSUS_API_KEY','AUTOAXE_FRED_API_KEY')) {
    $secret = Read-Host "Enter $name (blank if unused)" -AsSecureString
    $value = [System.Net.NetworkCredential]::new('', $secret).Password
    if ($value) { [Environment]::SetEnvironmentVariable($name, $value, 'Process') }
    Remove-Variable secret, value
}
$env:AUTOAXE_SEC_CONTACT = Read-Host 'Enter actual name or organization and email'
```

현재 PowerShell 및 자식 프로세스에만 적용되며 창을 닫으면 사라집니다. 상시 운영에서는 배포 환경의 비밀 저장소에서 재시작 시 주입하도록 설정합니다.

### Docker Compose

기존 배포 설정과 함께 네 환경변수를 Compose 실행 환경에 주입합니다. 별도 환경 파일을 사용한다면 Git 추적 대상 밖의 접근 제한된 위치에 보관하고 `--env-file`로 지정합니다.

```dotenv
AUTOAXE_BEA_API_KEY=
AUTOAXE_CENSUS_API_KEY=
AUTOAXE_FRED_API_KEY=
AUTOAXE_SEC_CONTACT=
```

빈 값에 실제 정보를 넣으세요. 기존 DB·네트워크 변수도 공급해야 합니다. 리포지토리 루트에서 설정 문법을 검증하는 예:

```sh
docker compose --env-file /path/to/private.env -f infra/compose/phase2-collectors.yaml --profile approved config --quiet
```

예시 경로는 실제 파일 위치로 교체하세요. 이 검사는 수집기 시작이나 API 인증 확인이 아닙니다. 키를 변경했으면 기존 컨테이너를 재생성하여 적용합니다. 기본 명령은 도움말 출력이므로 실제 실행 및 지속 운영은 [배포 안내](../../infra/compose/README.md)를 따릅니다.

## 7. 설정 확인 및 문제 해결

```powershell
foreach ($name in @('AUTOAXE_BEA_API_KEY','AUTOAXE_CENSUS_API_KEY','AUTOAXE_FRED_API_KEY','AUTOAXE_SEC_CONTACT')) {
    $configured = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))
    Write-Output "$name configured=$configured"
}
```

True는 값이 설정됐다는 뜻이며 인증 성공을 보장하지 않습니다. 실제 수집 상태는 수집기 실행 결과와 데이터 최신성으로 확인합니다.

| 증상 | 조치 |
|---|---|
| 발급 메일 미수신 | 주소 및 스팸함 확인, 공식 지원 문의 |
| 키 인증 오류 | 활성화 여부, 복사 오류, 공급자 일치 여부 확인 |
| SEC 요청 실패 | 실제 연락처와 대상 CIK 확인 |
| HTTP 403/429 | 수집 중단, 이용 조건 및 호출 제한 확인 |
| 재시작 후 설정 누락 | 비밀 주입 설정 확인 및 컨테이너 재생성 |

## 8. 보안 및 운영 주의사항

실제 키를 Git, 채팅, 명령 기록, 로그, 프런트엔드에 넣지 않습니다. 환경변수 전체 또는 Compose config 전체 출력도 공유하지 않습니다. 유출 시 공식 절차로 폐기·재발급하고 기존 수집 환경을 갱신합니다. 키 등록만으로 수집 권한 및 운영 승인이 자동 활성화되지는 않습니다.
