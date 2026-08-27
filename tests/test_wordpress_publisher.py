"""modules/wordpress_publisher 테스트.

실제 WordPress 사이트는 호출하지 않는다 — WordPressClient를
MagicMock으로 대체한다.
"""
from unittest.mock import MagicMock

from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content
from modules.master_content.schema import MasterContent, WordPressContent
from modules.quality_gate.models import (
    PublicationDecision,
    QualityGateResult,
    RecommendedStatus,
    ScoreBreakdown,
)
from modules.wordpress_publisher.models import PublishAction
from modules.wordpress_publisher.publisher import publish_to_wordpress
from modules.wordpress_writer.fact_validation import FactValidationStatus

SAMPLE_INPUT = "data/input/sample_market_data.json"


def _content_with_wordpress() -> MasterContent:
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="FOMC 브리핑", market_data=market_data)
    content.wordpress = WordPressContent(
        title="FOMC 브리핑: 금리 동결",
        slug="fomc-briefing-rate-hold",
        excerpt="이번 FOMC 결정을 요약한다.",
        content_html="<h2>핵심 답변</h2><p>기준금리가 동결되었다.</p>",
    )
    return content


def _gate_result(status: FactValidationStatus, warnings: list[str] | None = None) -> QualityGateResult:
    return QualityGateResult(
        status=status,
        scores=ScoreBreakdown(fact=90, seo=90, aeo=90, geo=90, neo=90, overall=90),
        warnings=warnings or [],
    )


def _decision_for(status: FactValidationStatus) -> PublicationDecision:
    if status == FactValidationStatus.PASS:
        return PublicationDecision(
            publish_ready=True, recommended_status=RecommendedStatus.PUBLISH, reason="PASS"
        )
    if status == FactValidationStatus.REVIEW_REQUIRED:
        return PublicationDecision(
            publish_ready=False, recommended_status=RecommendedStatus.DRAFT, reason="REVIEW_REQUIRED"
        )
    return PublicationDecision(publish_ready=False, recommended_status=RecommendedStatus.BLOCKED, reason="FAIL")


def _mock_client(find_result: dict | None = None) -> MagicMock:
    client = MagicMock()
    client.find_post_by_slug.return_value = find_result
    client.create_post.return_value = {"id": 1, "link": "https://example.com/?p=1", "status": "draft"}
    client.update_post.return_value = {"id": 1, "link": "https://example.com/?p=1", "status": "draft"}
    return client


# ---- 7. PASS + draft-first=true → draft ----


def test_pass_with_draft_first_true_creates_draft():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client()
    client.create_post.return_value = {"id": 5, "link": "https://x/?p=5", "status": "draft"}

    outcome = publish_to_wordpress(content, gate, decision, client=client, dry_run=False, draft_first=True)

    assert outcome.action == PublishAction.CREATED
    assert outcome.wordpress_status == "draft"
    _, kwargs = client.create_post.call_args
    assert kwargs["status"] == "draft"
    assert content.publish.published is False
    assert content.publish.post_id == 5


# ---- 8. PASS + draft-first=false → publish ----


def test_pass_with_draft_first_false_publishes():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client()
    client.create_post.return_value = {"id": 6, "link": "https://x/?p=6", "status": "publish"}

    outcome = publish_to_wordpress(content, gate, decision, client=client, dry_run=False, draft_first=False)

    assert outcome.action == PublishAction.CREATED
    assert outcome.wordpress_status == "publish"
    _, kwargs = client.create_post.call_args
    assert kwargs["status"] == "publish"
    assert content.publish.published is True


# ---- 9. REVIEW_REQUIRED → 항상 draft ----


def test_review_required_always_drafts_even_with_draft_first_false():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.REVIEW_REQUIRED, warnings=["SEO 점수 미달"])
    decision = _decision_for(FactValidationStatus.REVIEW_REQUIRED)
    client = _mock_client()

    outcome = publish_to_wordpress(content, gate, decision, client=client, dry_run=False, draft_first=False)

    assert outcome.wordpress_status == "draft"
    _, kwargs = client.create_post.call_args
    assert kwargs["status"] == "draft"
    assert outcome.warnings == ["SEO 점수 미달"]


# ---- 10. FAIL → WordPress client 호출 안 함 ----


def test_fail_never_calls_wordpress_client():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.FAIL)
    decision = _decision_for(FactValidationStatus.FAIL)
    client = _mock_client()

    outcome = publish_to_wordpress(content, gate, decision, client=client, dry_run=False, draft_first=True)

    assert outcome.action == PublishAction.BLOCKED
    client.find_post_by_slug.assert_not_called()
    client.create_post.assert_not_called()
    client.update_post.assert_not_called()


def test_fail_never_calls_wordpress_client_even_in_dry_run_false_config_default():
    # dry_run을 아예 지정하지 않아도(=.env 기본값 True) FAIL은 그 이전에 이미 차단된다.
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.FAIL)
    decision = _decision_for(FactValidationStatus.FAIL)
    client = _mock_client()

    publish_to_wordpress(content, gate, decision, client=client)

    client.create_post.assert_not_called()


# ---- 11. dry-run=true → API 호출 안 함 ----


def test_dry_run_never_calls_wordpress_client():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client()

    outcome = publish_to_wordpress(content, gate, decision, client=client, dry_run=True, draft_first=True)

    assert outcome.dry_run is True
    client.find_post_by_slug.assert_not_called()
    client.create_post.assert_not_called()


# ---- 12. dry-run 결과 정확성 ----


def test_dry_run_result_reflects_would_be_action():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)

    outcome = publish_to_wordpress(
        content, gate, decision, client=_mock_client(), dry_run=True, draft_first=False
    )

    assert outcome.action == PublishAction.DRY_RUN
    assert outcome.wordpress_status == "publish"  # draft_first=False이므로 publish가 "예정"
    assert outcome.title == content.wordpress.title
    assert outcome.slug == content.wordpress.slug
    assert outcome.quality_status == "PASS"


def test_dry_run_result_reflects_draft_when_draft_first_true():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)

    outcome = publish_to_wordpress(
        content, gate, decision, client=_mock_client(), dry_run=True, draft_first=True
    )

    assert outcome.wordpress_status == "draft"


# ---- 13. 동일 slug 존재 + policy=skip → 생성 안 함 ----


def test_existing_slug_with_skip_policy_does_not_create():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client(find_result={"id": 9, "link": "https://x/?p=9", "status": "draft"})

    outcome = publish_to_wordpress(
        content, gate, decision, client=client, dry_run=False, draft_first=True, existing_post_policy="skip"
    )

    assert outcome.action == PublishAction.SKIPPED
    client.create_post.assert_not_called()
    client.update_post.assert_not_called()


def test_existing_published_post_is_never_updated_even_with_draft_update_policy():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client(find_result={"id": 10, "link": "https://x/?p=10", "status": "publish"})

    outcome = publish_to_wordpress(
        content,
        gate,
        decision,
        client=client,
        dry_run=False,
        draft_first=True,
        existing_post_policy="draft_update",
    )

    assert outcome.action == PublishAction.SKIPPED
    client.update_post.assert_not_called()
    assert content.publish.published is True
    assert content.publish.post_id == 10


def test_existing_draft_with_draft_update_policy_updates():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client(find_result={"id": 11, "link": "https://x/?p=11", "status": "draft"})
    client.update_post.return_value = {"id": 11, "link": "https://x/?p=11", "status": "draft"}

    outcome = publish_to_wordpress(
        content,
        gate,
        decision,
        client=client,
        dry_run=False,
        draft_first=True,
        existing_post_policy="draft_update",
    )

    assert outcome.action == PublishAction.UPDATED
    client.update_post.assert_called_once()
    client.create_post.assert_not_called()


# ---- 15/16. content/title/slug/excerpt 매핑 ----


def test_content_and_metadata_mapping_to_wordpress_payload():
    content = _content_with_wordpress()
    gate = _gate_result(FactValidationStatus.PASS)
    decision = _decision_for(FactValidationStatus.PASS)
    client = _mock_client()

    publish_to_wordpress(content, gate, decision, client=client, dry_run=False, draft_first=True)

    _, kwargs = client.create_post.call_args
    assert kwargs["title"] == content.wordpress.title
    assert kwargs["content_html"] == content.wordpress.content_html
    assert kwargs["excerpt"] == content.wordpress.excerpt
    assert kwargs["slug"] == content.wordpress.slug
