<#
.SYNOPSIS
    Market-Dashboard(돈맥 콘텐츠 자동화 시스템) Windows 초기 설정 스크립트.

.DESCRIPTION
    새 Windows PC에서 이 저장소를 clone한 뒤, 복잡한 수동 설정 없이
    실행 환경을 갖추기 위한 스크립트다. Python/Git 확인, pip 확인,
    PYTHONUTF8 설정, requirements.txt 설치, .env 생성(기존 .env는
    절대 덮어쓰지 않음), .env의 git 추적 제외 여부 확인, WordPress/
    Anthropic 관련 환경변수의 "설정됨/없음" 여부만 확인한다.

    보안: 이 스크립트는 어떤 API 키/토큰/client secret 값도 화면에
    출력하지 않는다. 오직 "configured"/"missing" 여부만 보여준다.

.PARAMETER CheckOnly
    이 스위치를 주면 아무 것도 설치/생성/수정하지 않고, 현재 환경
    상태만 점검해서 보여준다(패키지 설치 없음, .env 생성 없음,
    PYTHONUTF8 영구 설정 없음).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1 -CheckOnly
#>

[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [경고] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "  [오류] $Message" -ForegroundColor Red
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# .env 스타일 파일에서 특정 키의 "원본 값"을 읽는다. 절대 화면에
# 그대로 출력하지 않고 호출자가 configured/missing 판정에만 쓴다.
function Get-DotEnvValue {
    param(
        [string]$Name,
        [string]$EnvFilePath
    )
    if (-not (Test-Path $EnvFilePath)) {
        return $null
    }
    $pattern = "^\s*$([regex]::Escape($Name))\s*="
    $line = Select-String -Path $EnvFilePath -Pattern $pattern | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    $raw = $line.Line
    $eqIndex = $raw.IndexOf("=")
    if ($eqIndex -lt 0) {
        return $null
    }
    return $raw.Substring($eqIndex + 1).Trim()
}

function Test-DotEnvConfigured {
    param(
        [string]$Name,
        [string]$EnvFilePath
    )
    $value = Get-DotEnvValue -Name $Name -EnvFilePath $EnvFilePath
    return -not [string]::IsNullOrWhiteSpace($value)
}

function Write-ConfiguredStatus {
    param(
        [string]$Name,
        [string]$EnvFilePath
    )
    if (Test-DotEnvConfigured -Name $Name -EnvFilePath $EnvFilePath) {
        Write-Host "  $Name : configured" -ForegroundColor Green
    } else {
        Write-Host "  $Name : missing" -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------
# 0. 저장소 루트로 이동 (이 스크립트가 있는 위치 기준)
# ---------------------------------------------------------------------

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

Write-Host "Market-Dashboard Windows 초기 설정" -ForegroundColor Magenta
if ($CheckOnly) {
    Write-Host "(-CheckOnly 모드: 아무 것도 설치/생성/수정하지 않고 점검만 합니다)" -ForegroundColor Magenta
}

$EnvFilePath = Join-Path $RepoRoot ".env"
$EnvExamplePath = Join-Path $RepoRoot ".env.example"

# ---------------------------------------------------------------------
# 1. Python / Git 확인
# ---------------------------------------------------------------------

Write-Section "필수 도구 확인"

if (-not (Test-CommandExists "python")) {
    Write-Err "python 명령을 찾을 수 없습니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요."
    exit 1
}
Write-Ok "python 명령을 찾았습니다."

if (-not (Test-CommandExists "git")) {
    Write-Err "git 명령을 찾을 수 없습니다. https://git-scm.com/downloads 에서 설치 후 다시 실행하세요."
    exit 1
}
Write-Ok "git 명령을 찾았습니다."

$pythonVersion = (python --version) 2>&1
Write-Host "  Python 버전: $pythonVersion"

try {
    $pipVersion = (python -m pip --version) 2>&1
    Write-Ok "pip 사용 가능: $pipVersion"
} catch {
    Write-Err "pip을 사용할 수 없습니다. Python 설치 시 pip 포함 옵션을 확인하세요."
    exit 1
}

# ---------------------------------------------------------------------
# 2. PYTHONUTF8=1 설정 (한글 텍스트 처리를 위해 필요)
# ---------------------------------------------------------------------

Write-Section "PYTHONUTF8 설정"

if ($CheckOnly) {
    $currentUserValue = [Environment]::GetEnvironmentVariable("PYTHONUTF8", "User")
    if ($currentUserValue -eq "1") {
        Write-Ok "PYTHONUTF8=1 (User 환경변수에 이미 설정되어 있습니다)"
    } else {
        Write-Warn "PYTHONUTF8이 설정되어 있지 않습니다 (-CheckOnly 모드라 변경하지 않습니다)."
    }
} else {
    $currentUserValue = [Environment]::GetEnvironmentVariable("PYTHONUTF8", "User")
    if ($currentUserValue -ne "1") {
        [Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
        Write-Ok "PYTHONUTF8=1 을 User 환경변수로 저장했습니다(다음 터미널부터 적용)."
    } else {
        Write-Ok "PYTHONUTF8=1 이 이미 설정되어 있습니다."
    }
    $env:PYTHONUTF8 = "1"
    Write-Ok "현재 세션에도 PYTHONUTF8=1 을 적용했습니다."
}

# ---------------------------------------------------------------------
# 3. requirements.txt 설치
# ---------------------------------------------------------------------

Write-Section "Python 패키지 설치"

$RequirementsPath = Join-Path $RepoRoot "requirements.txt"

if ($CheckOnly) {
    if (Test-Path $RequirementsPath) {
        Write-Ok "requirements.txt 를 찾았습니다 (-CheckOnly 모드라 설치하지 않습니다)."
    } else {
        Write-Warn "requirements.txt 를 찾을 수 없습니다."
    }
} else {
    if (-not (Test-Path $RequirementsPath)) {
        Write-Err "requirements.txt 를 찾을 수 없습니다: $RequirementsPath"
        exit 1
    }
    python -m pip install --upgrade pip
    python -m pip install -r $RequirementsPath
    Write-Ok "requirements.txt 설치를 완료했습니다."
}

# ---------------------------------------------------------------------
# 4. .env 존재 확인 / 생성 (기존 .env는 절대 덮어쓰지 않음)
# ---------------------------------------------------------------------

Write-Section ".env 파일 확인"

if (Test-Path $EnvFilePath) {
    Write-Ok ".env 파일이 이미 있습니다. 기존 파일을 덮어쓰지 않습니다."
} else {
    if ($CheckOnly) {
        Write-Warn ".env 파일이 없습니다 (-CheckOnly 모드라 생성하지 않습니다)."
    } else {
        if (-not (Test-Path $EnvExamplePath)) {
            Write-Err ".env.example 을 찾을 수 없어 .env 를 생성할 수 없습니다: $EnvExamplePath"
            exit 1
        }
        Copy-Item -Path $EnvExamplePath -Destination $EnvFilePath
        Write-Ok ".env.example 을 복사해 .env 를 생성했습니다. notepad .env 로 실제 값을 입력하세요."
    }
}

# ---------------------------------------------------------------------
# 5. .env 가 git에서 제외되는지 확인
# ---------------------------------------------------------------------

Write-Section ".env 의 git 추적 제외 확인"

if (Test-Path $EnvFilePath) {
    git check-ignore -q ".env"
    if ($LASTEXITCODE -eq 0) {
        Write-Ok ".env 는 .gitignore 에 의해 git 추적에서 제외됩니다."
    } else {
        Write-Warn ".env 가 git에서 제외되지 않는 것으로 보입니다. .gitignore 를 확인하세요 (절대 git add/commit 하지 마세요)."
    }
} else {
    Write-Warn ".env 파일이 없어 gitignore 여부를 확인할 수 없습니다."
}

# ---------------------------------------------------------------------
# 6. WordPress OAuth 관련 환경변수 - 설정됨/없음 여부만 확인 (재사용 지원)
# ---------------------------------------------------------------------

Write-Section "WordPress 인증 정보 확인 (값은 출력하지 않습니다)"

$WordPressVars = @(
    "WORDPRESS_AUTH_MODE",
    "WORDPRESS_COM_SITE_ID",
    "WORDPRESS_COM_ACCESS_TOKEN",
    "WORDPRESS_COM_CLIENT_ID",
    "WORDPRESS_COM_CLIENT_SECRET",
    "WORDPRESS_COM_REDIRECT_URI"
)

foreach ($varName in $WordPressVars) {
    Write-ConfiguredStatus -Name $varName -EnvFilePath $EnvFilePath
}

if (Test-DotEnvConfigured -Name "WORDPRESS_COM_ACCESS_TOKEN" -EnvFilePath $EnvFilePath) {
    Write-Ok "기존 WORDPRESS_COM_ACCESS_TOKEN 을 재사용합니다. 새로 OAuth 인증할 필요가 없습니다."
} else {
    Write-Warn "WORDPRESS_COM_ACCESS_TOKEN 이 없습니다. 다음 명령으로 OAuth 인증을 진행하세요:"
    Write-Host "    py main.py --wordpress-oauth-setup" -ForegroundColor White
}

# ---------------------------------------------------------------------
# 7. Anthropic API 키 확인 - 설정됨/없음 여부만 확인
# ---------------------------------------------------------------------

Write-Section "Anthropic API 설정 확인 (값은 출력하지 않습니다)"

if (Test-DotEnvConfigured -Name "ANTHROPIC_API_KEY" -EnvFilePath $EnvFilePath) {
    Write-Host "ANTHROPIC_API_KEY: configured" -ForegroundColor Green
} else {
    Write-Host "ANTHROPIC_API_KEY: missing" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------
# 8. 안전 기본값(dry-run / draft-first) 확인 - 자동 수정하지 않고 경고만
# ---------------------------------------------------------------------

Write-Section "안전 기본값 확인 (자동으로 변경하지 않습니다)"

$dryRunValue = Get-DotEnvValue -Name "WORDPRESS_DRY_RUN" -EnvFilePath $EnvFilePath
if ($null -ne $dryRunValue -and $dryRunValue.Trim().ToLower() -eq "false") {
    Write-Warn "WORDPRESS_DRY_RUN=false 로 설정되어 있습니다. 실제 WordPress API를 호출합니다. 의도한 것이 맞는지 확인하세요."
} else {
    Write-Ok "WORDPRESS_DRY_RUN 은 안전한 기본값(true 또는 미설정)입니다."
}

$draftFirstValue = Get-DotEnvValue -Name "WORDPRESS_DRAFT_FIRST" -EnvFilePath $EnvFilePath
if ($null -ne $draftFirstValue -and $draftFirstValue.Trim().ToLower() -eq "false") {
    Write-Warn "WORDPRESS_DRAFT_FIRST=false 로 설정되어 있습니다. PASS 판정 시 바로 publish될 수 있습니다. 의도한 것이 맞는지 확인하세요."
} else {
    Write-Ok "WORDPRESS_DRAFT_FIRST 는 안전한 기본값(true 또는 미설정)입니다."
}

# ---------------------------------------------------------------------
# 9. 다음 단계 안내
# ---------------------------------------------------------------------

Write-Section "다음 단계"

Write-Host "  1) notepad .env  (필요한 값 입력: ANTHROPIC_API_KEY, WordPress 설정 등)"
if (-not (Test-DotEnvConfigured -Name "WORDPRESS_COM_ACCESS_TOKEN" -EnvFilePath $EnvFilePath)) {
    Write-Host "  2) py main.py --wordpress-oauth-setup  (WordPress.com OAuth 인증)"
    Write-Host "  3) py main.py --wordpress-test  (WordPress 연결 확인)"
    Write-Host "  4) py main.py --input data/input/sample_treasury_buyback.json --publish --dry-run  (dry-run 실행 확인)"
} else {
    Write-Host "  2) py main.py --wordpress-test  (WordPress 연결 확인)"
    Write-Host "  3) py main.py --input data/input/sample_treasury_buyback.json --publish --dry-run  (dry-run 실행 확인)"
}

Write-Host ""
Write-Host "설정 스크립트를 완료했습니다." -ForegroundColor Magenta
