"""돈맥 콘텐츠 자동화 시스템 - CLI 진입점.

사용 예:
    python main.py --topic "미국 증시 브리핑" --input data/input/sample_market_data.json

실제 LLM(Anthropic)으로 dry-run을 테스트해보려면, facts/sources가
없는 샘플 시세 데이터보다 아래처럼 facts/sources가 채워진 확장 입력을
쓰는 것을 권장한다 (그래야 LLM이 근거 없는 숫자를 옮겨 적어 Fact
Grounding 검증에 걸리는 일이 줄어든다). data/input/sample_treasury_buyback.json
은 그런 형식의 "테스트 전용" 샘플이며 topic도 파일 안에 있어 --topic을
생략할 수 있다:
    python main.py --input data/input/sample_treasury_buyback.json --publish --dry-run

WordPress.com OAuth2 access token이 아직 없다면 먼저:
    python main.py --wordpress-oauth-setup
(.env의 WORDPRESS_COM_CLIENT_ID/CLIENT_SECRET/REDIRECT_URI/SITE_ID 가
채워져 있어야 하며, curl을 직접 만들 필요 없이 브라우저 인가 → code
붙여넣기 → access token 발급까지 대화형으로 진행한다.)

WordPress 연동은 항상 안전한 순서로 확인한다.
    1) 연결만 확인:      python main.py --wordpress-test
    2) dry-run으로 확인: python main.py --topic "테스트" --publish --dry-run
    3) 그다음에만 실제로 draft 생성: python main.py --topic "테스트" --publish
       (WORDPRESS_DRY_RUN=false 로 .env를 바꾸기 전에는 --publish 를 줘도
       WORDPRESS_DRY_RUN 기본값(true) 때문에 여전히 dry-run으로 동작한다.)
"""
from __future__ import annotations

import argparse
import logging

from clients.wordpress_client import WordPressClient, WordPressClientError
from clients.wordpress_oauth_setup import run_oauth_setup
from config.settings import get_settings
from modules.master_content.schema import MasterContent
from modules.quality_gate.gate import decide_publication, run_quality_gate_for_content
from pipeline.orchestrator import run_pipeline
from pipeline.quality_report import build_quality_gate_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="돈맥 콘텐츠 자동화 파이프라인 실행")
    parser.add_argument(
        "--topic",
        help="콘텐츠 주제 (예: '미국 증시 브리핑'). 입력 파일에 \"topic\" 필드가 있으면 생략 가능하다.",
    )
    parser.add_argument(
        "--input",
        default="data/input/sample_market_data.json",
        help="시장 데이터 JSON 파일 경로. market_data만 담은 기존 형식과, "
        "{\"topic\", \"market_data\", \"analysis\"}를 함께 담은 확장 형식을 모두 지원한다.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Quality Gate 판정에 따라 WordPress 발행(또는 draft/dry-run)을 시도한다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="WordPress API를 전혀 호출하지 않고 결과만 미리 보여준다 "
        "(WORDPRESS_DRY_RUN 기본값이 이미 true라 --publish만 줘도 보통 dry-run이다).",
    )
    parser.add_argument(
        "--wordpress-test",
        action="store_true",
        help="다른 작업 없이 WordPress 연결(인증정보)만 확인하고 종료한다.",
    )
    parser.add_argument(
        "--wordpress-oauth-setup",
        action="store_true",
        help="WordPress.com OAuth2 access token 발급을 대화형으로 진행하고 "
        ".env에 저장한 뒤 종료한다 (curl을 직접 만들 필요 없음).",
    )
    return parser.parse_args()


def _run_wordpress_connection_test() -> None:
    try:
        client = WordPressClient()
        result = client.test_connection()
    except WordPressClientError as exc:
        print(f"WordPress 연결 실패: {exc}")
        raise SystemExit(1)

    name = result.get("name") or result.get("slug") or "(알 수 없음)"
    print(f"WordPress 연결 성공: 사용자={name}")


def _print_quality_gate_report(content: MasterContent) -> None:
    """--publish 실행 후 Quality Gate 판정을 사람이 읽을 수 있게 출력한다.

    content.wordpress(3단계에서 생성 완료된 값)만으로 다시 계산하므로
    WordPress API를 호출하지 않는다. get_settings()로 읽는 wordpress_
    draft_first는 실제 publish_to_wordpress()가 쓴 것과 같은 값이라
    "WordPress 예정 status"가 실제 발행 로직과 어긋나지 않는다.
    """
    gate_result = run_quality_gate_for_content(content)
    decision = decide_publication(gate_result)
    draft_first = get_settings().wordpress_draft_first
    print(build_quality_gate_report(gate_result, decision, draft_first=draft_first))


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    args = parse_args()

    if args.wordpress_oauth_setup:
        succeeded = run_oauth_setup()
        raise SystemExit(0 if succeeded else 1)

    if args.wordpress_test:
        _run_wordpress_connection_test()
        return

    try:
        content = run_pipeline(
            topic=args.topic,
            market_data_path=args.input,
            publish=args.publish,
            dry_run=True if args.dry_run else None,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))

    print(f"완료: {content.meta.id}")
    print(f"품질 검사 통과 여부: {content.quality_check.overall_passed}")
    if not content.quality_check.overall_passed:
        for channel in ("seo", "aeo", "geo", "neo"):
            result = getattr(content.quality_check, channel)
            for issue in result.issues:
                print(f"  [{channel.upper()}] {issue}")

    if args.publish:
        _print_quality_gate_report(content)


if __name__ == "__main__":
    main()
