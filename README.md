# 돈맥 콘텐츠 자동화 시스템

금융/거시경제 데이터를 하나의 **Master Content JSON**으로 구조화하고,
이를 기반으로 WordPress 분석글 · Threads 글 · NotebookLM 영상 원고 ·
YouTube 메타데이터 · 썸네일 프롬프트까지 한 번에 생성하는 콘텐츠
자동화 파이프라인입니다.

> 현재 상태: **프로젝트 뼈대(스켈레톤) 단계**입니다. 전체 흐름은
> 실제로 동작하지만, WordPress 발행 / LLM 연동 / Search Console 연동은
> 아직 자리만 잡아둔 상태(placeholder)입니다. 자세한 구현 순서는
> 아래 "다음 구현 단계"와 `CLAUDE.md`를 참고하세요.

## 전체 흐름 (10단계)

```
1. 금융/거시경제 데이터 입력           (modules/data_ingest)
2. Master Content JSON으로 구조화      (modules/master_content)
3. WordPress 분석글 생성               (modules/wordpress_writer)
4. SEO/AEO/GEO/NEO 품질 검사           (modules/quality_check)
5. 통과한 콘텐츠만 WordPress 발행       (modules/wordpress_publisher)  [아직 미구현]
6. Threads 글 생성                     (modules/threads_writer)
7. NotebookLM 영상 원고 생성            (modules/notebooklm_script)
8. YouTube 제목/설명/챕터/고정댓글      (modules/youtube_meta)
9. Midjourney/Canva 썸네일 프롬프트     (modules/thumbnail_prompt)
10. 성과 데이터 기록 (Search Console 등) (modules/performance_tracker) [아직 미구현]
```

모든 단계는 **하나의 `MasterContent` 객체**를 받아서 자기 담당 필드만
채운 뒤 그대로 반환합니다. 그래서 어떤 모듈이든 다른 모듈 없이
단독으로 테스트할 수 있습니다. 자세한 설계 배경은 `CLAUDE.md`를
참고하세요.

## 기술 스택

- **Python 3.11+**
- `pydantic` — Master Content JSON 스키마 정의/검증
- `python-dotenv` — `.env` 파일로 환경변수 로드
- `requests` — WordPress REST API 등 외부 API 호출 (추후 사용)
- `pytest` — 테스트
- (추후) `openai` 또는 `anthropic` — 콘텐츠 생성용 LLM
- (추후) `google-api-python-client` — Google Search Console 연동

## 폴더 구조

```
Market-Dashboard/
├── main.py                     # CLI 진입점 (파이프라인 실행)
├── requirements.txt
├── pytest.ini
├── .env.example                 # 환경변수 템플릿 (실제 값은 .env 에 작성, git에는 올리지 않음)
├── config/
│   └── settings.py              # .env 로드 + 전역 설정 (모든 API 키는 여기서만 읽음)
├── data/
│   ├── input/                   # 원본 입력 데이터 (예: 시장 데이터 JSON)
│   ├── master/                  # 생성된 Master Content JSON 저장 위치 (git 미포함)
│   └── output/                  # 채널별 산출물 저장 위치 (git 미포함)
├── modules/                     # 파이프라인 각 단계 (독립적으로 테스트 가능)
│   ├── data_ingest/              # 1단계
│   ├── master_content/           # 2단계 (스키마 + 빌더)
│   ├── wordpress_writer/         # 3단계
│   ├── quality_check/            # 4단계 (seo/aeo/geo/neo 개별 파일 + 통합 checker)
│   ├── wordpress_publisher/      # 5단계 (아직 미구현)
│   ├── threads_writer/           # 6단계
│   ├── notebooklm_script/        # 7단계
│   ├── youtube_meta/             # 8단계
│   ├── thumbnail_prompt/         # 9단계
│   └── performance_tracker/      # 10단계
├── clients/                     # 외부 API 클라이언트 (아직 미구현, 뼈대만)
│   ├── wordpress_client.py
│   ├── llm_client.py
│   └── search_console_client.py
├── pipeline/
│   └── orchestrator.py          # 1~10단계를 순서대로 실행
└── tests/                       # 모듈별/파이프라인 전체 테스트
```

## 실행 방법 (초보자용)

### 1. Python 설치 확인

터미널에서 아래 명령으로 Python 3.11 이상이 있는지 확인합니다.

```bash
python3 --version
```

### 2. 가상환경 생성 및 활성화

프로젝트 폴더 안에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows는: .venv\Scripts\activate
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 환경변수 파일 생성

```bash
cp .env.example .env
```

`.env` 파일을 열어서 실제로 가지고 있는 값만 채워 넣으세요.
`ANTHROPIC_API_KEY`는 3단계(WordPress 글 생성)에서 실제로 사용하므로,
`python main.py`를 그대로 실행하려면 이 값을 채워야 합니다. (테스트는
가짜 LLM 응답을 쓰기 때문에 키가 없어도 `pytest`는 그대로 통과합니다.)
`--publish`로 WordPress 발행까지 시도하려면 `WORDPRESS_URL`/
`WORDPRESS_USERNAME`/`WORDPRESS_APP_PASSWORD`도 채워야 합니다(안
채워도 파이프라인 자체는 4단계까지 동작합니다). `WORDPRESS_DRY_RUN`/
`WORDPRESS_DRAFT_FIRST`는 기본값이 이미 안전(`true`)하므로 그대로
두는 것을 권장합니다 — 자세한 확인 순서는 아래 "WordPress 발행을
실제로 확인하는 안전한 순서" 참고.

### 5. 파이프라인 실행

샘플 데이터로 전체 파이프라인을 한 번 실행해봅니다.

```bash
python main.py --topic "미국 증시 브리핑" --input data/input/sample_market_data.json
```

실행이 끝나면:
- `data/master/<id>.json` 에 Master Content JSON이 저장됩니다.
- 콘솔에 SEO/AEO/GEO/NEO 품질 검사 통과 여부와 미통과 사유가 출력됩니다.

나만의 데이터로 실행하고 싶다면 `data/input/sample_market_data.json`
과 같은 형식으로 새 JSON 파일을 만들고 `--input` 옵션에 경로를
넘기면 됩니다.

실제 Anthropic LLM으로 dry-run을 테스트해보고 싶다면(`--publish
--dry-run`), `sample_market_data.json`처럼 `analysis.facts/sources`가
비어 있는 입력보다 `data/input/sample_treasury_buyback.json`을 쓰는
것을 권장합니다. 이 파일은 `{"topic", "market_data", "analysis"}`를
함께 담은 확장 입력 형식으로, facts/sources가 채워져 있어 LLM이 근거
없는 숫자를 만들어 Fact Grounding 검증에 걸리는 일이 줄어듭니다(테스트
전용 합성 데이터이며, 파일의 `market_data.notes`에 명시되어 있습니다).
`topic`도 파일 안에 있어 `--topic`을 생략할 수 있습니다:

```bash
python main.py --input data/input/sample_treasury_buyback.json --publish --dry-run
```

### 6. 테스트 실행

각 모듈이 잘 동작하는지 확인합니다.

```bash
pytest
```

## 지금 할 수 있는 것 / 아직 안 되는 것

| 단계 | 상태 |
|---|---|
| 1. 데이터 입력 | ✅ JSON 파일 기반으로 동작 (`market_data`만 담은 기존 형식 + `{"topic", "market_data", "analysis"}`를 함께 담은 확장 형식 모두 지원) |
| 2. Master JSON 구조화 | ✅ 동작 (`analysis` 필드: primary_question/facts/sources/bull·bear case 등 포함) |
| 3. WordPress 글 생성 | ✅ Anthropic Claude 기반 실제 생성 (WordPressArticle 스키마 검증 + Fact Grounding 검증 포함) |
| 4. 품질 검사 | ✅ 규칙 기반으로 동작 (기준은 추후 조정 가능) |
| 5. WordPress 발행 | ✅ 실제 REST API 연동 (`clients/wordpress_client.py`). 기본값은 항상 안전(dry-run + draft-first) |
| 6~9. 채널별 콘텐츠 생성 | ⚠️ 템플릿 기반 placeholder (아직 LLM 미연동, wordpress 결과만 재사용) |
| 10. 성과 기록 | ❌ 미구현 |
| LLM 클라이언트 (`clients/llm_client.py`) | ✅ Anthropic Claude API 연동 (wordpress_writer 에서 사용 중) |
| Quality Gate (`modules/quality_gate/`) | ✅ fact/seo/aeo/geo/neo 점수 + PASS/REVIEW_REQUIRED/FAIL + 발행 여부 결정. `run_quality_gate_for_content()`로 파이프라인 5단계에 연결됨 |

## WordPress 발행을 실제로 확인하는 안전한 순서

WordPress 인증 방식은 두 가지이며 `WORDPRESS_AUTH_MODE`로 선택합니다.

- `app_password`(기본): self-hosted WordPress. `WORDPRESS_URL`/
  `WORDPRESS_USERNAME`/`WORDPRESS_APP_PASSWORD`를 채웁니다.
- `wordpress_com_oauth2`: Application Password를 지원하지 않는
  WordPress.com Free 플랜용. `WORDPRESS_COM_SITE_ID`(사이트 도메인 또는
  숫자 site ID)와 `WORDPRESS_COM_ACCESS_TOKEN`(OAuth2 access token)을
  채웁니다. access token이 아직 없다면 curl을 직접 만들 필요 없이:

  1. [developer.wordpress.com/apps](https://developer.wordpress.com/apps/new/)
     에서 "Web" 타입 앱을 등록하고 `WORDPRESS_COM_CLIENT_ID`/
     `WORDPRESS_COM_CLIENT_SECRET`/`WORDPRESS_COM_REDIRECT_URI`를 `.env`에
     채웁니다(`WORDPRESS_COM_SITE_ID`도 필요).
  2. `python main.py --wordpress-oauth-setup` 실행 → 필요한 값이 있으면
     WordPress.com 인가(authorization) URL을 자동으로 브라우저에서 열고
     (안 열리면 URL만 출력), 승인 후 리다이렉트된 URL 전체(또는 code
     값만)를 터미널에 붙여넣으면 access token을 발급받아 `.env`의
     `WORDPRESS_COM_ACCESS_TOKEN`만 갱신합니다(다른 값/순서는 보존, 갱신
     전 `.env.bak.<시각>` 백업 자동 생성). access token/client secret/
     code는 화면에 출력되지 않습니다.

`.env`에 해당 방식의 값을 채운 뒤:

1. **연결만 확인**: `python main.py --wordpress-test`
2. **dry-run으로 전체 파이프라인 확인** (WordPress API를 전혀 호출하지 않음):
   `python main.py --topic "테스트" --publish --dry-run`
   (`WORDPRESS_DRY_RUN` 기본값이 이미 `true`라 `--dry-run` 없이 `--publish`만
   줘도 여전히 dry-run으로 동작합니다.)
3. **그다음에만 실제 draft 생성**: `.env`는 그대로 두고(`WORDPRESS_DRAFT_FIRST=true`
   유지) `python main.py --topic "테스트" --publish` — 품질 검사를 통과해도
   WordPress에는 draft로만 만들어집니다. 운영자가 `.env`에서
   `WORDPRESS_DRAFT_FIRST=false`로 의도적으로 바꾸기 전에는 자동 공개
   발행되지 않습니다.

## 다음 구현 단계

1. `modules/threads_writer`, `notebooklm_script`, `youtube_meta`,
   `thumbnail_prompt` — placeholder 로직을
   `clients/llm_client.LlmClient.generate()` 호출로 교체 (wordpress_writer와
   동일한 패턴: MasterContent만 근거로 삼고, LLM 응답은 구조화된 스키마로
   검증한 뒤에만 반영)
2. `clients/search_console_client.py` + `modules/performance_tracker`
   — Google Search Console 연동
3. Evergreen 페이지 업데이트(기존 published 글 자동 갱신) 정책 —
   이번 단계에서는 의도적으로 만들지 않음

각 단계의 상세한 작업 원칙과 설계 규칙은 `CLAUDE.md`를 참고하세요.
