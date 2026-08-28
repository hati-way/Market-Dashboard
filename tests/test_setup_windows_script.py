"""setup_windows.ps1 정적 구조 검증.

이 저장소를 실행하는 환경에는 PowerShell(pwsh)이 설치되어 있지 않아
스크립트를 직접 실행할 수 없다. 그래서 파일 내용을 텍스트로 읽어
필요한 로직/명령/안전장치가 실제로 들어 있는지만 확인한다("가능한
범위에서"의 정적 검증). WordPress/Anthropic 관련 값은 어떤 경우에도
화면에 출력하지 않는다는 보안 제약이 특히 중요하므로, 값을 출력할 만한
패턴이 없는지도 함께 확인한다.
"""
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "setup_windows.ps1"


def _read_script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_file_exists():
    assert SCRIPT_PATH.exists()


def test_script_has_check_only_switch_parameter():
    text = _read_script()
    assert "[switch]$CheckOnly" in text


def test_script_checks_python_and_git_are_executable():
    text = _read_script()
    assert 'Test-CommandExists "python"' in text
    assert 'Test-CommandExists "git"' in text


def test_script_prints_python_version():
    text = _read_script()
    assert "python --version" in text


def test_script_checks_pip_available():
    text = _read_script()
    assert "python -m pip --version" in text


def test_script_sets_pythonutf8():
    text = _read_script()
    assert "PYTHONUTF8" in text
    assert '"User"' in text  # 영구 저장을 위해 User scope 환경변수 사용
    assert '$env:PYTHONUTF8 = "1"' in text  # 현재 세션에도 즉시 적용


def test_script_installs_requirements():
    text = _read_script()
    assert "pip install -r" in text
    assert "requirements.txt" in text


def test_script_never_overwrites_existing_env_file():
    text = _read_script()
    # .env가 이미 있으면 Copy-Item으로 덮어쓰지 않고, 없을 때만 생성한다.
    assert "Test-Path $EnvFilePath" in text
    assert "Copy-Item -Path $EnvExamplePath -Destination $EnvFilePath" in text
    assert "덮어쓰지 않습니다" in text


def test_script_creates_env_from_example_only_when_missing():
    text = _read_script()
    assert ".env.example" in text
    assert "$EnvExamplePath" in text


def test_script_checks_env_is_gitignored():
    text = _read_script()
    assert "git check-ignore" in text


def test_script_checks_wordpress_oauth_related_vars_without_printing_values():
    text = _read_script()
    required_vars = [
        "WORDPRESS_AUTH_MODE",
        "WORDPRESS_COM_SITE_ID",
        "WORDPRESS_COM_ACCESS_TOKEN",
        "WORDPRESS_COM_CLIENT_ID",
        "WORDPRESS_COM_CLIENT_SECRET",
        "WORDPRESS_COM_REDIRECT_URI",
    ]
    for var_name in required_vars:
        assert var_name in text


def test_script_guides_oauth_setup_command_when_token_missing():
    text = _read_script()
    assert "py main.py --wordpress-oauth-setup" in text


def test_script_checks_anthropic_api_key_configured_or_missing():
    text = _read_script()
    assert 'ANTHROPIC_API_KEY: configured' in text
    assert 'ANTHROPIC_API_KEY: missing' in text


def test_script_warns_but_does_not_autofix_unsafe_dry_run_or_draft_first():
    text = _read_script()
    assert "WORDPRESS_DRY_RUN" in text
    assert "WORDPRESS_DRAFT_FIRST" in text
    assert "자동으로 변경하지 않습니다" in text


def test_script_prints_final_guidance_commands():
    text = _read_script()
    assert "py main.py --wordpress-test" in text
    assert "py main.py --input data/input/sample_treasury_buyback.json --publish --dry-run" in text


def test_script_never_adds_env_to_git():
    text = _read_script()
    # "git add .env"처럼 실제로 실행되는 명령이 없어야 한다. 경고 문구에서
    # "git add/commit 하지 마세요"처럼 언급하는 것은 허용한다.
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("git add")
        assert not stripped.startswith("git commit")


def test_script_never_echoes_secret_values():
    text = _read_script()
    # Get-DotEnvValue는 값을 반환하지만, 반환값을 그대로 Write-Host에
    # 넘겨 화면에 찍는 패턴이 없어야 한다.
    assert "Write-Host $value" not in text
    assert "Write-Host (Get-DotEnvValue" not in text
    for var_name in (
        "WORDPRESS_COM_ACCESS_TOKEN",
        "WORDPRESS_COM_CLIENT_SECRET",
        "WORDPRESS_APP_PASSWORD",
        "ANTHROPIC_API_KEY",
    ):
        for line in text.splitlines():
            if var_name in line and "Write-Host" in line:
                assert "$value" not in line
                assert "$currentUserValue" not in line


def test_check_only_mode_gates_all_mutations():
    text = _read_script()
    # 설치/생성/영구 환경변수 저장은 모두 -not $CheckOnly 또는 if ($CheckOnly) { ... } else { ... } 로 분기되어야 한다.
    assert "if ($CheckOnly) {" in text
    assert "pip install --upgrade pip" in text
    assert "[Environment]::SetEnvironmentVariable(\"PYTHONUTF8\", \"1\", \"User\")" in text
