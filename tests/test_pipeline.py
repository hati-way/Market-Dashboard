from unittest.mock import MagicMock

from modules.master_content.schema import ContentStatus
from pipeline.orchestrator import run_pipeline

SAMPLE_INPUT = "data/input/sample_market_data.json"


def test_run_pipeline_end_to_end(fake_llm_client):
    content = run_pipeline(
        topic="파이프라인 통합 테스트",
        market_data_path=SAMPLE_INPUT,
        llm_client=fake_llm_client,
    )

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


# ---- 17. orchestrator end-to-end mocked integration ----


def test_run_pipeline_with_publish_dry_run_does_not_call_wordpress(fake_llm_client):
    """publish=True 여도 dry_run=True(기본값)면 WordPress API를 절대 부르지 않는다."""
    content = run_pipeline(
        topic="파이프라인 발행 dry-run 테스트",
        market_data_path=SAMPLE_INPUT,
        llm_client=fake_llm_client,
        publish=True,
        dry_run=True,
    )

    assert content.wordpress.content_html
    # dry-run이므로 MasterContent.publish 는 변경되지 않아야 한다.
    assert content.publish.published is False
    assert content.publish.post_id is None

    import os

    saved_path = f"data/master/{content.meta.id}.json"
    assert os.path.exists(saved_path)
    os.remove(saved_path)


def test_run_pipeline_with_publish_and_mocked_wordpress_client(fake_llm_client):
    """publish=True + dry_run=False + 가짜 WordPressClient 주입으로 전체 흐름을 확인한다.

    wordpress_writer -> Fact Grounding -> Quality Gate -> Publication
    Decision -> wordpress_publisher 가 실제로 이어지는지 검증한다.
    """
    mock_wp_client = MagicMock()
    mock_wp_client.find_post_by_slug.return_value = None
    mock_wp_client.create_post.return_value = {
        "id": 42,
        "link": "https://example.com/?p=42",
        "status": "draft",
    }

    content = run_pipeline(
        topic="파이프라인 실발행 통합 테스트",
        market_data_path=SAMPLE_INPUT,
        llm_client=fake_llm_client,
        publish=True,
        dry_run=False,
        draft_first=True,
        wordpress_client=mock_wp_client,
    )

    mock_wp_client.create_post.assert_called_once()
    assert content.publish.post_id == 42
    assert content.publish.post_url == "https://example.com/?p=42"

    import os

    saved_path = f"data/master/{content.meta.id}.json"
    assert os.path.exists(saved_path)
    os.remove(saved_path)
