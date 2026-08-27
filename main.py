"""돈맥 콘텐츠 자동화 시스템 - CLI 진입점.

사용 예:
    python main.py --topic "미국 증시 브리핑" --input data/input/sample_market_data.json
"""
from __future__ import annotations

import argparse
import logging

from config.settings import get_settings
from pipeline.orchestrator import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="돈맥 콘텐츠 자동화 파이프라인 실행")
    parser.add_argument("--topic", required=True, help="콘텐츠 주제 (예: '미국 증시 브리핑')")
    parser.add_argument(
        "--input",
        default="data/input/sample_market_data.json",
        help="시장 데이터 JSON 파일 경로",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="품질 검사를 통과하면 WordPress 발행을 시도한다 (아직 미구현).",
    )
    return parser.parse_args()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    args = parse_args()
    content = run_pipeline(topic=args.topic, market_data_path=args.input, publish=args.publish)

    print(f"완료: {content.meta.id}")
    print(f"품질 검사 통과 여부: {content.quality_check.overall_passed}")
    if not content.quality_check.overall_passed:
        for channel in ("seo", "aeo", "geo", "neo"):
            result = getattr(content.quality_check, channel)
            for issue in result.issues:
                print(f"  [{channel.upper()}] {issue}")


if __name__ == "__main__":
    main()
