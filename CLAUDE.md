# CLAUDE.md

이 문서는 Claude Code(또는 다른 AI 코딩 에이전트)가 이 저장소에서
작업할 때 지켜야 할 아키텍처 규칙과 구현 순서를 정리한 것입니다.

## 프로젝트 개요

"돈맥 콘텐츠 자동화 시스템"은 금융/거시경제 데이터를 입력받아 하나의
Master Content JSON으로 구조화하고, 이를 기반으로 WordPress 분석글,
Threads 글, NotebookLM 영상 원고, YouTube 메타데이터, 썸네일 프롬프트를
자동 생성하는 파이프라인입니다. 발행은 SEO/AEO/GEO/NEO 품질 검사를
통과한 콘텐츠에 한해서만 이루어집니다.

전체 흐름은 `README.md`의 "전체 흐름 (10단계)" 표를 참고하세요.

## 핵심 설계 원칙

1. **단일 데이터 구조(Single Source of Truth)**
   모든 모듈은 `modules/master_content/schema.py`의 `MasterContent`
   객체 하나를 입력받고, 자기 담당 필드만 채운 뒤 그대로 반환한다.
   함수 시그니처는 항상 `def do_something(content: MasterContent) -> MasterContent`
   형태를 유지한다. 이렇게 해야:
   - 각 모듈을 다른 모듈 없이 독립적으로 테스트할 수 있고
   - `pipeline/orchestrator.py`에서 단계를 자유롭게 추가/제거/순서
     변경할 수 있다.

2. **모듈 = 폴더 단위 독립 단위**
   `modules/<단계이름>/` 각각은 다른 `modules/*` 패키지에 의존하지
   않는다 (오직 `modules/master_content`의 스키마 타입만 가져다
   쓴다). 한 모듈을 통째로 삭제해도 다른 모듈이 깨지지 않아야 한다.

3. **외부 API 접근은 항상 `clients/`를 통해서만**
   WordPress, LLM(OpenAI/Anthropic), Search Console, Threads 등
   외부 서비스 호출 코드는 `clients/*_client.py`에만 존재한다.
   `modules/*`는 이 클라이언트를 가져다 쓰기만 하고, `requests`나
   SDK를 직접 import 하지 않는다. → 나중에 공급자를 바꾸거나
   모킹(mock)해서 테스트하기 쉬워진다.

4. **비밀값은 오직 `config/settings.py`를 통해서만 읽는다**
   - API 키, 비밀번호, URL 등 민감한 값은 **절대 코드에 하드코딩하지
     않는다.**
   - 모든 값은 `.env` 파일 → `config/settings.get_settings()` 를
     거쳐서만 읽는다.
   - 새 환경변수가 필요하면 반드시: `.env.example`에 키 추가 →
     `config/settings.py`의 `Settings` 데이터클래스에 필드 추가 →
     `get_settings()`에서 로드. 이 세 곳을 항상 함께 수정한다.
   - `.env` 파일 자체는 git에 커밋하지 않는다 (`.gitignore`에 등록됨).

5. **바로 실사용 기능을 완성하려 하지 않는다**
   이 저장소는 단계적으로 구현한다. 아직 구현되지 않은 외부 연동은
   `NotImplementedError`를 던지는 명확한 stub으로 남겨두고, 함수
   시그니처와 반환 타입만 먼저 확정한다. 새 기능을 구현할 때도
   가능하면 먼저 인터페이스(입출력 타입)를 정하고, 그 다음에 내부
   로직을 채운다.

## 폴더별 역할

| 경로 | 역할 |
|---|---|
| `config/settings.py` | `.env` 로드 + 전역 설정 (모든 비밀값의 유일한 출처) |
| `modules/master_content/schema.py` | Master Content JSON의 pydantic 스키마 정의 (가장 먼저 봐야 할 파일) |
| `modules/master_content/builder.py` | MasterContent 생성/저장/로드 |
| `modules/data_ingest/` | 1단계: 원본 데이터 → `MarketData` 변환 |
| `modules/wordpress_writer/` | 3단계: `MasterContent` → `wordpress` 필드 채움. Anthropic Claude 실제 연동, `models.py`(WordPressArticle), `markdown_html.py`(안전한 마크다운→HTML 변환), `fact_validation.py`(Fact ID·숫자/날짜 근거 검증) 포함 |
| `modules/quality_check/` | 4단계(파이프라인 원래 단계): seo/aeo/geo/neo 개별 checker + 통합 `checker.py` (규칙 기반 pass/fail, 점수 없음) |
| `modules/quality_gate/` | WordPressArticle 발행 전 최종 판정. fact/seo/aeo/geo/neo 0~100점 + PASS/REVIEW_REQUIRED/FAIL + `decide_publication()`. `run_quality_gate_for_content(content)`로 생성이 끝난 MasterContent에서 바로 돌릴 수 있다. `modules/quality_check/`와 별개 모듈(의도적으로 통합하지 않음, 아래 참고) |
| `modules/wordpress_publisher/` | 5단계: 실제 WordPress 발행. `models.py`(PublishOutcome/PublishAction). 기본값은 항상 dry-run + draft-first(안전) |
| `modules/threads_writer/`, `notebooklm_script/`, `youtube_meta/`, `thumbnail_prompt/` | 6~9단계: 채널별 콘텐츠 생성 |
| `modules/performance_tracker/` | 10단계: 성과 기록 (현재 미구현) |
| `clients/` | 외부 API 클라이언트 (`llm_client.py`=Anthropic, `wordpress_client.py`=WordPress REST API 연동 완료, `wordpress_oauth_setup.py`=WordPress.com OAuth2 access token 발급 로컬 helper, 나머지는 stub) |
| `pipeline/orchestrator.py` | 전체 단계를 순서대로 실행하는 오케스트레이터 |
| `main.py` | CLI 진입점 |
| `tests/` | 모듈별 + 파이프라인 전체 테스트 |
| `.claude/skills/fire-your-seo-agency/` | 프로젝트 전용 설치(전역 아님). SEO/AEO/GEO/LLMO/NEO 참고 자료. 실제로 무엇을 가져오고 안 가져왔는지는 `PROJECT_NOTES.md` 참고 |

## 구현 순서 (로드맵)

이미 완료됨:
- [x] Master Content JSON 스키마 (`modules/master_content/schema.py`)
- [x] `analysis` 섹션 (`Fact`/`Source`/`Analysis`): primary_question,
      summary, facts, sources, causal_chain, market_implications,
      bull_case, bear_case, risks, invalidating_conditions,
      update_triggers, confidence. `Fact`는 claim/source 필수, 날짜는
      ISO 형식만 허용, source_type/confidence는 Enum으로 값 제한
      (`tests/test_master_content_validation.py`)
- [x] 5~9단계 중 6~9단계는 placeholder 구현 (LLM 없이도 동작)
- [x] SEO/AEO/GEO/NEO 규칙 기반 품질 검사
- [x] `pipeline/orchestrator.py`, `main.py` (`llm_client`를 주입할 수 있게
      선택적 파라미터로 열어둠)
- [x] LLM 클라이언트 (`clients/llm_client.py`, Anthropic Claude 연동,
      `generate(user_prompt, system_prompt=None, max_tokens=..., timeout=...,
      extra_options=...)` 단일 인터페이스). Claude Sonnet 5는
      temperature/top_p/top_k 같은 비기본 sampling 옵션을 보내면 오류가
      날 수 있어 기본 경로에서는 아예 보내지 않는다. 모델별 옵션은
      extra_options(→ extra_body)로만 확장한다. `LlmConfigError`/
      `LlmRetryableError`/`LlmFatalError` 구분, mocking 테스트
      `tests/test_llm_client.py`
- [x] **3단계: `modules/wordpress_writer` 를 Anthropic Claude 기반 실제
      생성으로 교체.** MasterContent.market_data + analysis 를 JSON으로
      프롬프트에 명시적으로 넣고, "제공된 MasterContent만 사실의
      근거로 사용한다"는 원칙을 system prompt에 포함. LLM 응답은
      `modules/wordpress_writer/models.WordPressArticle` 로 파싱/검증한
      뒤에만 반영(파싱 실패 시 `WordPressGenerationError`). content_html은
      LLM 값을 신뢰하지 않고 `markdown_html.markdown_to_html()`로 시스템이
      직접 변환(허용 문법 외 텍스트는 escape). source_list도 LLM 값을
      무시하고 `MasterContent.analysis.sources/facts`에서 시스템이 직접
      생성. 본문의 소수점 숫자가 MasterContent에 실제로 존재하는지
      최소한으로 검증해 없는 숫자가 있으면 `HallucinationDetectedError`.
      `generate_wordpress_content(content, llm_client=None)`처럼
      `llm_client`를 주입할 수 있어 테스트가 실제 API를 부르지 않는다.
      테스트: `tests/test_wordpress_writer.py`, 공용 fixture는
      `tests/conftest.py`의 `FakeLlmClient`/`fake_llm_client`.
- [x] **Fact Grounding 강화** (`modules/wordpress_writer/fact_validation.py`).
      `Fact`에 `id` 필드 추가(직접 안 정할 경우 `Analysis`가 순서대로
      "fact_001"처럼 자동 채번, `Analysis._assign_fact_ids`). LLM은
      `WordPressArticle.used_fact_ids`로 근거 fact id를 함께 반환하고,
      시스템은 이를 그대로 신뢰하지 않고 `validate_fact_grounding()`으로
      검증한다: 존재하지 않는 fact id, 퍼센트/bp/억·조·billion 등
      규모 표현/날짜(ISO, "YYYY년 M월 D일", 연도 없는 "M월 D일")를
      MasterContent와 대조 → `FactValidationResult(status=PASS|
      REVIEW_REQUIRED|FAIL, used_fact_ids, invalid_fact_ids,
      unsupported_claims, unsupported_numbers, warnings)`. FAIL은
      `FactGroundingError`로 막아 `content.wordpress`에 반영되지 않고,
      REVIEW_REQUIRED(예: confidence=low fact 사용, used_fact_ids가
      비었는데 본문에 구체적 수치가 있음)는 막지 않지만
      `WordPressContent.fact_validation_status/warnings`(신규 additive
      필드)에 남겨 향후 draft 게이트에 쓸 수 있게 해 둔다. 목록/heading
      번호("1.", "##")는 검사 전에 줄 앞에서 제거해 사실 숫자로 오인하지
      않는다. `source_list`도 검증된 `used_fact_ids`가 있으면 그 fact의
      source를 최우선으로 쓰도록 `_build_source_list`를 확장했다(없으면
      기존처럼 analysis.sources 전체 → 모든 fact.source 순으로 폴백).
      테스트: `tests/test_fact_validation.py` (14개).
- [x] **`.claude/skills/fire-your-seo-agency/` 설치(프로젝트 전용)** —
      [leopard627/fire-your-seo-agency](https://github.com/leopard627/fire-your-seo-agency)
      (MIT). 설치 전 SKILL.md/plugin.json/marketplace.json을 직접 읽고
      자동 실행 스크립트·postinstall 훅이 없음을 확인한 뒤 참고 문서만
      수동으로 복사했다(플러그인 마켓플레이스 경유 설치 아님). 어떤
      원칙을 가져오고 안 가져왔는지는 `PROJECT_NOTES.md`에 정리.
- [x] **`modules/quality_gate/`** — WordPressArticle 발행 전 최종 판정.
      fact/seo/aeo/geo/neo 0~100점 + `overall`(가중평균, fact 35% 비중
      최대) 계산, `PASS`/`REVIEW_REQUIRED`/`FAIL` 판정, `decide_publication()`
      으로 `publish_ready`/`recommended_status`(publish/draft/blocked)
      결정. **Fact Validation이 점수보다 항상 우선**: FAIL이면 SEO 점수가
      100이어도 전체 FAIL. 모든 임계값은 `quality_gate/config.py`
      (`QualityGateConfig`) 한 곳에서만 관리하고 각 score_*.py는 그 값을
      읽기만 한다. `modules/quality_check/`(기존, 규칙 기반 pass/fail)는
      건드리지 않았고 의도적으로 통합하지 않았다(둘의 목적이 다름).
      본문을 임의로 수정하지 않고 검사만 한다. 테스트:
      `tests/test_quality_gate.py` (14개).
- [x] **WordPress 실제 발행 연동 + Quality Gate 파이프라인 연결.**
      `clients/wordpress_client.py`: `WORDPRESS_AUTH_MODE`로 두 인증
      방식 중 선택. 기본값 `app_password`는 self-hosted WordPress의
      Application Password(HTTP Basic Auth)로 `{WORDPRESS_URL}/wp-json/
      wp/v2/*` 를 호출한다. `wordpress_com_oauth2`는 Application
      Password를 지원하지 않는 WordPress.com Free 플랜용으로, OAuth2
      access token(Bearer 인증)으로 `https://public-api.wordpress.com/
      wp/v2/sites/{WORDPRESS_COM_SITE_ID}/*` 를 호출한다(토큰 발급 자체는
      이 클라이언트 밖에서 이미 끝났다고 가정). 두 모드 모두 `test_connection`/
      `create_post`/`update_post`/`get_post`/`find_post_by_slug`
      인터페이스와 재시도/에러 분류 로직을 공유한다. timeout/연결
      오류/429/5xx는 `WordPressRetryableError`(최대 재시도 횟수는
      `WORDPRESS_MAX_RETRIES`로 설정), 4xx는 `WordPressFatalError`로
      구분. 인증정보(Basic auth 튜플 또는 Bearer 토큰)는 요청 자체에만
      실어 보내고 로그/예외 메시지에 절대 남기지 않는다.
      `modules/wordpress_publisher/`: Quality
      Gate 결과(`QualityGateResult`)와 `PublicationDecision`을 받아
      `PublishOutcome`(action/wordpress_status/post_id/url 등)을 반환.
      **기본값은 항상 안전한 쪽**: `WORDPRESS_DRY_RUN=true`(기본)면
      WordPress API를 전혀 호출하지 않고, `WORDPRESS_DRAFT_FIRST=true`
      (기본)면 PASS여도 곧바로 publish하지 않고 draft로 낮춘다.
      REVIEW_REQUIRED는 draft-first 설정과 무관하게 항상 draft, FAIL은
      dry-run 여부와 무관하게 WordPress API를 절대 호출하지 않는다.
      같은 slug가 이미 있으면 기본 정책(`WORDPRESS_EXISTING_POST_POLICY=
      skip`)은 아무것도 하지 않고, 이미 발행(publish)된 글은
      `draft_update` 정책이어도 절대 자동 수정하지 않는다.
      `pipeline/orchestrator.py`는 `publish=True`일 때만
      `quality_gate.run_quality_gate_for_content()` →
      `decide_publication()` → `publish_to_wordpress()`를 순서대로
      호출한다(`WordPressContent`에 새로 추가한 `used_fact_ids` 필드로
      생성 시점의 Fact Grounding 검증 결과를 재구성). `main.py`에
      `--wordpress-test`(연결 확인) / `--dry-run` 플래그 추가. 테스트:
      `tests/test_wordpress_client.py`(18개, WordPress.com OAuth2
      모드 7개 포함), `tests/test_wordpress_publisher.py`
      (12개), `tests/test_pipeline.py`에 통합 테스트 2개 추가.
- [x] **WordPress.com OAuth2 access token 발급 자동화**
      (`clients/wordpress_oauth_setup.py`, `--wordpress-oauth-setup`).
      `WORDPRESS_COM_CLIENT_ID`/`CLIENT_SECRET`/`REDIRECT_URI`/`SITE_ID`
      누락 여부만 확인(값은 절대 출력 안 함) → authorization URL 생성 →
      `webbrowser.open()`으로 자동으로 열어보고 실패하면 URL만 출력 →
      사용자가 붙여넣은 리다이렉트 URL 전체 또는 code 값에서
      `extract_code_from_input()`으로 code만 추출 → WordPress.com
      token endpoint 호출 → 성공 시 `.env`를 먼저
      `.env.bak.<UTC타임스탬프>`로 백업(`.gitignore`에 `.env.bak*`
      추가)한 뒤 `update_env_file()`로 `WORDPRESS_COM_ACCESS_TOKEN` 줄만
      정규식으로 찾아 교체(다른 줄의 내용/순서는 그대로 보존, 없으면
      끝에 추가). `client_secret`/authorization code/access_token은
      로그·예외 메시지·화면 출력 어디에도 남기지 않는다. 대화형 I/O
      (`input_func`/`open_browser_func`/`print_func`)를 주입 가능하게
      만들어 실제 브라우저/터미널 없이 테스트한다. 이 모듈은
      `WordPressClient`/`pipeline/orchestrator.py`가 전혀 참조하지
      않는 로컬 전용 setup helper다. 테스트:
      `tests/test_wordpress_oauth_setup.py`(22개, 실제 .env는
      건드리지 않고 tmp_path만 사용).
- [x] 기본 테스트 스위트
- [x] **`modules/wordpress_writer` 생성 품질 개선(구조/문체, Fact
      Grounding·Quality Gate·Publisher는 미변경).** 시스템 프롬프트
      (`generator.py`의 `_SYSTEM_PROMPT`)를 8섹션 한글 구조로 단순화하고
      ("Bull case"/"Bear case"/"thesis"/"invalidation" 같은 영어 소제목
      금지), 인과관계는 화살표로 잇는 단정 대신 조건부 문장으로,
      confidence=low/secondary 근거는 "일부 시장 참여자는 ~라고 본다"
      식으로 주체+불확실성을 함께 쓰도록 지침을 추가했다. AI 리포트
      상투어(“제공된 분석에 따르면” 등) 금지, 분량 목표(1,500~2,500자),
      제목 가이드(간결하게, 클릭베이트 금지)도 명시했다.
      `WordPressArticle`에 `seo_title`(선택, 기본 "")을 추가해 화면
      H1(`title`)과 검색용 title을 분리할 수 있게 하되, 비어 있으면
      기존처럼 `title`을 그대로 meta title로 쓴다(하위 호환).
      `_build_source_list()`는 "기관명 — 기준일 — URL" 형태로 출처를
      만들고(날짜/URL은 항상 MasterContent의 Fact.date/Source.url에서만
      가져오고 새로 만들지 않음), URL이 없으면 "URL 미제공", 2차
      출처인데 URL도 없으면 그 한계를 문구로 명시한다. 출처 HTML
      블록의 URL은 `<a>` 링크로 렌더링해 Quality Gate의 "본문에 링크
      없음" 권고가 실제 출처로 자연스럽게 해소되게 했다(quality_gate
      쪽 검사 로직 자체는 손대지 않음). `Analysis.internal_links`
      (신규, `InternalLink(title, url)` 목록, 기본 빈 목록) 필드를
      추가해 있으면 "관련 글" 섹션을 만들고, 없으면 내부링크를 전혀
      만들지 않는다(가짜 URL 금지). 기존 `source_list`/저확신도 관련
      테스트 2건은 새 출력 형식/문구에 맞춰 값만 갱신했고, Fact
      Grounding/Quality Gate/Publisher 코드는 전혀 수정하지 않았다.
      테스트: `tests/test_wordpress_writer_style.py`(17개, 새 스타일
      규칙 + seo_title + 출처/내부링크 + 기존 Fact Grounding이 새
      구조에서도 그대로 동작하는지 확인).

다음에 할 일 (권장 순서):

1. **나머지 콘텐츠 생성 모듈을 LLM 기반으로 교체**
   - `threads_writer`, `notebooklm_script`, `youtube_meta`,
     `thumbnail_prompt`를 `wordpress_writer`와 같은 패턴으로 교체:
     MasterContent(+ 이미 생성된 wordpress 필드)를 근거로 프롬프트를
     만들고, 구조화된 스키마로 응답을 파싱/검증한 뒤에만 반영
   - 각 모듈의 함수 시그니처는 바꾸지 않는다 (`MasterContent -> MasterContent`),
     테스트 가능하도록 `llm_client` 주입 파라미터를 추가한다
2. **`modules/analysis` (또는 유사한) 모듈 추가 검토**
   - 지금은 `analysis` 필드를 채우는 전용 모듈이 없어 테스트/수동으로
     직접 채워야 한다. market_data → analysis 를 채우는 단계를 LLM
     기반으로 새로 만들지, 3단계(wordpress_writer) 이전에 별도 단계로
     둘지 결정 필요
3. **Quality Gate 점수 캘리브레이션** — `modules/quality_gate/seo_score.py`
   등의 휴리스틱(keyword_repetition_ratio, 문단 길이 등)은 실제 생성된
   글로 임계값을 재검증할 필요가 있음
4. **Evergreen 페이지 자동 업데이트** — 지금은 이미 발행된 글을 절대
   자동 수정하지 않는다(`WORDPRESS_EXISTING_POST_POLICY`가
   `draft_update`여도 마찬가지). 발행된 글을 최신 데이터로 갱신하는
   기능은 별도 정책/모듈로 설계 필요
5. **Search Console 연동** — `clients/search_console_client.py` +
   `modules/performance_tracker/tracker.py`
   - 발행된 글의 URL을 기준으로 성과 데이터를 주기적으로 수집해
     `MasterContent.performance`에 append
6. **Threads API 연동** (선택) — 지금은 텍스트만 생성하고 실제
   게시는 하지 않음. 필요 시 `clients/threads_client.py`를 새로
   추가하고 동일한 패턴을 따른다.

## 새 외부 연동을 추가할 때 체크리스트

1. `clients/<service>_client.py` 에 클라이언트 클래스 추가 (생성자에서
   `config.settings.get_settings()`로 필요한 값만 읽기)
2. 필요한 환경변수를 `.env.example`과 `config/settings.py`에 추가
3. 해당 클라이언트를 사용하는 `modules/*` 함수는 여전히
   `MasterContent -> MasterContent` 시그니처 유지
4. 외부 API를 직접 호출하지 않는 단위 테스트를 `tests/`에 추가
   (클라이언트는 모킹하거나, 클라이언트 호출 이전 로직만 테스트)
5. `README.md`의 "지금 할 수 있는 것 / 아직 안 되는 것" 표 갱신

## 테스트

```bash
pytest
```

- 새 모듈을 추가하면 그 모듈만 단독으로 테스트하는 파일을
  `tests/test_<module>.py`로 추가한다 (다른 모듈에 의존하지 않는
  최소 입력으로).
- `pipeline/orchestrator.py`를 바꿀 때는 `tests/test_pipeline.py`의
  end-to-end 테스트가 여전히 통과하는지 확인한다.
