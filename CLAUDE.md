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
| `modules/quality_check/` | 4단계: seo/aeo/geo/neo 개별 checker + 통합 `checker.py` |
| `modules/wordpress_publisher/` | 5단계: 발행 (현재 미구현, `clients/wordpress_client.py` 완성 후 연결) |
| `modules/threads_writer/`, `notebooklm_script/`, `youtube_meta/`, `thumbnail_prompt/` | 6~9단계: 채널별 콘텐츠 생성 |
| `modules/performance_tracker/` | 10단계: 성과 기록 (현재 미구현) |
| `clients/` | 외부 API 클라이언트 (`llm_client.py`는 Anthropic 연동 완료, 나머지는 stub) |
| `pipeline/orchestrator.py` | 전체 단계를 순서대로 실행하는 오케스트레이터 |
| `main.py` | CLI 진입점 |
| `tests/` | 모듈별 + 파이프라인 전체 테스트 |

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
- [x] 기본 테스트 스위트

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
3. **품질 검사 고도화**
   - 지금은 규칙 기반(길이, 키워드 포함 여부)만 있음
   - 필요하면 LLM을 이용한 정성적 평가를 추가 (예: AEO 검사에서
     "이 글이 질문에 직접 답하는가"를 LLM에게 판단시키기)
   - NEO 기준은 아직 가정 단계이므로, 실제 기준이 정해지면
     `modules/quality_check/neo_checker.py`만 수정하면 됨
4. **WordPress 발행 연동** — `clients/wordpress_client.py` +
   `modules/wordpress_publisher/publisher.py`
   - WordPress REST API (`/wp-json/wp/v2/posts`)를 Application
     Password 인증으로 호출
   - `publish_to_wordpress()`가 `NotImplementedError` 대신 실제
     `PublishResult`를 반환하도록 완성
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
