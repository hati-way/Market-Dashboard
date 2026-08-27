from modules.master_content.schema import ContentStatus
from pipeline.orchestrator import run_pipeline

SAMPLE_INPUT = "data/input/sample_market_data.json"


def test_run_pipeline_end_to_end():
    content = run_pipeline(topic="파이프라인 통합 테스트", market_data_path=SAMPLE_INPUT)

    assert content.wordpress.content_html
    assert content.quality_check.checked_at is not None
    assert content.threads.posts
    assert content.notebooklm.script
    assert content.youtube.title
    assert content.thumbnail.midjourney_prompt
    assert content.meta.status in (ContentStatus.QUALITY_CHECKED, ContentStatus.QUALITY_FAILED)

    saved_path = f"data/master/{content.meta.id}.json"
    import os

    assert os.path.exists(saved_path)
    os.remove(saved_path)
