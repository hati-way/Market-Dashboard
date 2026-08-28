"""pipeline/quality_report.py 와 main.py의 Quality Gate CLI 리포트 테스트.

Quality Gate의 점수 계산/판정 기준(modules/quality_gate)은 이 테스트에서
바꾸지 않는다 - 이미 계산된 결과를 사람이 읽을 수 있게 "출력"하는
부분만 확인한다.
"""
import json
import os

import main
from modules.quality_gate.gate import decide_publication, run_quality_gate_for_content
from modules.quality_gate.models import (
    PublicationDecision,
    QualityGateResult,
    RecommendedStatus,
    ScoreBreakdown,
)
from modules.wordpress_writer.fact_validation import FactValidationStatus
from pipeline.orchestrator import run_pipeline
from pipeline.quality_report import build_quality_gate_report, resolve_wordpress_status

from .conftest import FakeLlmClient

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"


# ---- 1. 출력 형식: 요청받은 예시("Fact: 100 PASS" 등)와 일치하는지 ----


def test_report_shows_per_lane_scores_in_requested_format():
    gate_result = QualityGateResult(
        status=FactValidationStatus.REVIEW_REQUIRED,
        scores=ScoreBreakdown(fact=100, seo=86, aeo=78, geo=91, neo=82, overall=87),
        warnings=["AEO 점수(78)가 기준(80) 미달입니다."],
    )
    decision = PublicationDecision(
        publish_ready=False,
        recommended_status=RecommendedStatus.DRAFT,
        reason="AEO 점수(78)가 기준(80) 미달입니다.",
    )

    report = build_quality_gate_report(gate_result, decision, draft_first=True)

    assert "Fact: 100 PASS" in report
    assert "SEO: 86 PASS" in report
    assert "AEO: 78 REVIEW" in report
    assert "GEO: 91 PASS" in report
    assert "NEO: 82 PASS" in report
    assert "Overall: 87" in report
    assert "Quality Status: REVIEW_REQUIRED" in report


# ---- 2. REVIEW_REQUIRED가 된 이유가 한국어로 나오는지 ----


def test_report_explains_review_required_reason_in_korean():
    gate_result = QualityGateResult(
        status=FactValidationStatus.REVIEW_REQUIRED,
        scores=ScoreBreakdown(fact=90, seo=90, aeo=90, geo=90, neo=90, overall=90),
        warnings=["낮은 확신도(confidence=low)의 fact(fact_004)를 근거로 사용했습니다: 예시 주장."],
    )
    decision = PublicationDecision(
        publish_ready=False, recommended_status=RecommendedStatus.DRAFT, reason="REVIEW_REQUIRED"
    )

    report = build_quality_gate_report(gate_result, decision, draft_first=True)

    assert "Quality Status: REVIEW_REQUIRED" in report
    assert "낮은 확신도(confidence=low)의 fact(fact_004)를 근거로 사용했습니다" in report
    assert "warnings:" in report
    assert "recommendations:" in report
    assert "failures:" in report
    assert "  (없음)" in report  # failures가 비어 있음도 명시적으로 보여준다


# ---- 3. FAIL 상태에서는 Fact 레인이 FAIL로 표시되는지 ----


def test_report_shows_fact_lane_as_fail_when_fact_validation_fails():
    gate_result = QualityGateResult(
        status=FactValidationStatus.FAIL,
        scores=ScoreBreakdown(fact=35, seo=100, aeo=100, geo=100, neo=100, overall=68),
        failures=["Fact Validation = FAIL", "650.12 (MasterContent에 없는 수치)"],
    )
    decision = PublicationDecision(
        publish_ready=False, recommended_status=RecommendedStatus.BLOCKED, reason="Fact Validation = FAIL"
    )

    report = build_quality_gate_report(gate_result, decision, draft_first=True)

    assert "Fact: 35 FAIL" in report
    assert "Quality Status: FAIL" in report
    assert "Publication Decision: blocked" in report
    assert "WordPress 예정 status: (발행하지 않음)" in report


# ---- 4. PASS 상태에서는 모든 레인이 PASS이고 사유가 명확한지 ----


def test_report_pass_status_shows_all_lanes_pass_and_publish_status():
    gate_result = QualityGateResult(
        status=FactValidationStatus.PASS,
        scores=ScoreBreakdown(fact=100, seo=100, aeo=100, geo=100, neo=100, overall=100),
    )
    decision = PublicationDecision(
        publish_ready=True, recommended_status=RecommendedStatus.PUBLISH, reason="Quality Gate PASS"
    )

    report = build_quality_gate_report(gate_result, decision, draft_first=False)

    assert "Quality Status: PASS (사유: 모든 기준을 통과했습니다.)" in report
    assert "Publication Decision: publish" in report
    assert "WordPress 예정 status: publish" in report

    report_draft_first = build_quality_gate_report(gate_result, decision, draft_first=True)
    assert "WordPress 예정 status: draft" in report_draft_first


# ---- 5. resolve_wordpress_status: 실제 발행 로직과 같은 함수를 재사용하는지 ----


def test_resolve_wordpress_status_matches_publisher_behavior():
    blocked = PublicationDecision(
        publish_ready=False, recommended_status=RecommendedStatus.BLOCKED, reason="x"
    )
    review = PublicationDecision(
        publish_ready=False, recommended_status=RecommendedStatus.DRAFT, reason="x"
    )
    passed = PublicationDecision(
        publish_ready=True, recommended_status=RecommendedStatus.PUBLISH, reason="x"
    )

    assert resolve_wordpress_status(blocked, draft_first=True) is None
    assert resolve_wordpress_status(review, draft_first=False) == "draft"
    assert resolve_wordpress_status(passed, draft_first=True) == "draft"
    assert resolve_wordpress_status(passed, draft_first=False) == "publish"


# ---- 6. 비밀값이 출력에 절대 포함되지 않는지 ----


def test_report_never_contains_secret_looking_markers():
    gate_result = QualityGateResult(
        status=FactValidationStatus.REVIEW_REQUIRED,
        scores=ScoreBreakdown(fact=90, seo=90, aeo=90, geo=90, neo=90, overall=90),
        warnings=["SEO 점수(90)가 기준(80) 미달입니다."],
        recommendations=["meta description 길이를 조정하세요."],
    )
    decision = PublicationDecision(
        publish_ready=False, recommended_status=RecommendedStatus.DRAFT, reason="REVIEW_REQUIRED"
    )

    report = build_quality_gate_report(gate_result, decision, draft_first=True)

    lowered = report.lower()
    for marker in ("sk-ant", "bearer ", "authorization:", "api_key", "app_password", "access_token"):
        assert marker not in lowered


# ---- 7. main.py CLI: 실제 파이프라인 결과로 리포트를 출력하는지(통합) ----


def test_main_prints_quality_gate_report_for_review_required_case(capsys):
    """실제 dry-run 회귀 케이스(REVIEW_REQUIRED)를 재현해 main.py의 출력 함수가
    Quality Gate 리포트를 실제로 콘솔에 찍는지 확인한다."""
    article = {
        "title": "미국 재무부 바이백 확대, 금융시장에 주는 영향",
        "slug": "us-treasury-buyback-market-impact",
        "excerpt": "재무부의 분기 국채 바이백 확대가 채권·주식 시장에 미치는 영향을 정리한다.",
        "meta_description": "미국 재무부의 국채 바이백 확대 발표가 금리와 달러, 위험자산에 미치는 영향을 분석한다.",
        "content_markdown": (
            "## 핵심 답변\n"
            "미국 재무부가 분기 국채 바이백 규모를 300억 달러로 발표했다.\n\n"
            "## 무슨 일이 일어났나\n"
            "미국 10년물 국채금리는 4.05%로 전일 대비 0.03%p 하락했고, 달러 "
            "인덱스(DXY)는 101.2로 0.15% 상승했다. 일부 시장 참가자는 유동성 "
            "프리미엄이 완화될 것으로 본다.\n\n"
            "## 핵심 요약\n"
            "시장은 다음 지표를 주시하고 있다."
        ),
        "primary_keyword": "미국 재무부 바이백",
        "related_keywords": ["국채금리"],
        "used_fact_ids": ["fact_001", "fact_002", "fact_003", "fact_004"],
    }
    fake_client = FakeLlmClient(json.dumps(article, ensure_ascii=False))

    content = run_pipeline(
        topic=None,
        market_data_path=EXTENDED_INPUT,
        llm_client=fake_client,
        publish=True,
        dry_run=True,
    )
    try:
        gate_result = run_quality_gate_for_content(content)
        assert gate_result.status == FactValidationStatus.REVIEW_REQUIRED  # 이 회귀 케이스의 전제

        capsys.readouterr()  # run_pipeline 내부 로그성 출력은 버린다
        main._print_quality_gate_report(content)
        captured = capsys.readouterr()

        assert "=== Quality Gate 결과 ===" in captured.out
        assert "Quality Status: REVIEW_REQUIRED" in captured.out
        assert "WordPress 예정 status:" in captured.out
        assert "Publication Decision:" in captured.out
    finally:
        saved_path = f"data/master/{content.meta.id}.json"
        if os.path.exists(saved_path):
            os.remove(saved_path)
