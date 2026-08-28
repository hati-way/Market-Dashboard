"""Quality Gate 판정 결과를 CLI에서 사람이 읽을 수 있는 텍스트로 만든다.

modules/quality_gate 의 점수 계산/PASS·REVIEW_REQUIRED·FAIL 판정 기준은
전혀 건드리지 않는다. 이미 계산된 QualityGateResult/PublicationDecision을
읽어 사람이 이해하기 좋은 형태로 "출력"만 한다. 여기서 다루는 값은
점수/상태/실패·경고·개선 제안 문자열뿐이며, API key/token 같은 비밀값은
애초에 이 값들에 담기지 않으므로 노출될 일이 없다.
"""
from __future__ import annotations

from modules.quality_gate.config import DEFAULT_CONFIG, QualityGateConfig
from modules.quality_gate.models import PublicationDecision, QualityGateResult
from modules.wordpress_publisher.publisher import resolve_wordpress_status
from modules.wordpress_writer.fact_validation import FactValidationStatus


def _lane_label(score: int, minimum: int) -> str:
    """레인 하나의 점수를 기준(minimum)과 비교해 "PASS"/"REVIEW"로 표시한다.

    modules/quality_gate/gate.py의 run_quality_gate()가 경고를 추가하는
    조건(`lane.score < minimum`)과 동일한 기준을 그대로 재사용한다 -
    화면에 보여주는 라벨이 실제 판정과 어긋나지 않도록 하기 위함이다.
    """
    return "PASS" if score >= minimum else "REVIEW"


def _fact_label(gate_result: QualityGateResult) -> str:
    """Fact 레인만 따로 "PASS"/"REVIEW"/"FAIL"로 표시한다.

    Fact Validation이 FAIL이면 run_quality_gate()가 항상 "Fact Validation
    = FAIL" 문자열을 failures에 넣으므로 그것으로 FAIL을 식별한다(title/
    content 필수 필드 누락처럼 Fact와 무관한 다른 failures와 구분하기
    위함이다). FAIL이 아닌데 fact 점수가 100 미만이면, fact 점수를 깎는
    유일한 다른 경로는 REVIEW_REQUIRED를 유발하는 경고(예: 낮은 확신도
    fact 사용, 통화 불명확)뿐이므로 REVIEW로 표시한다.
    """
    if "Fact Validation = FAIL" in gate_result.failures:
        return "FAIL"
    if gate_result.scores.fact < 100:
        return "REVIEW"
    return "PASS"


def _reason_text(gate_result: QualityGateResult) -> str:
    """Quality Status가 PASS가 아닌 경우, 그렇게 된 이유를 사람이 읽을 수
    있는 한국어 문장으로 정리한다."""
    if gate_result.status == FactValidationStatus.FAIL:
        items = gate_result.failures or ["사유가 기록되지 않았습니다."]
    elif gate_result.status == FactValidationStatus.REVIEW_REQUIRED:
        items = gate_result.warnings or ["사유가 기록되지 않았습니다."]
    else:
        return "모든 기준을 통과했습니다."
    return " / ".join(items)


def _format_list(label: str, items: list[str]) -> list[str]:
    lines = [f"{label}:"]
    if not items:
        lines.append("  (없음)")
    else:
        lines.extend(f"  - {item}" for item in items)
    return lines


def build_quality_gate_report(
    gate_result: QualityGateResult,
    decision: PublicationDecision,
    *,
    draft_first: bool,
    config: QualityGateConfig = DEFAULT_CONFIG,
) -> str:
    """Quality Gate 판정 전체를 CLI에 출력할 여러 줄 텍스트로 만든다."""
    scores = gate_result.scores
    lines = [
        "=== Quality Gate 결과 ===",
        f"Fact: {scores.fact} {_fact_label(gate_result)}",
        f"SEO: {scores.seo} {_lane_label(scores.seo, config.seo_min)}",
        f"AEO: {scores.aeo} {_lane_label(scores.aeo, config.aeo_min)}",
        f"GEO: {scores.geo} {_lane_label(scores.geo, config.geo_min)}",
        f"NEO: {scores.neo} {_lane_label(scores.neo, config.neo_min)}",
        f"Overall: {scores.overall}",
        f"Quality Status: {gate_result.status.value} (사유: {_reason_text(gate_result)})",
        "",
    ]
    lines.extend(_format_list("failures", gate_result.failures))
    lines.append("")
    lines.extend(_format_list("warnings", gate_result.warnings))
    lines.append("")
    lines.extend(_format_list("recommendations", gate_result.recommendations))
    lines.append("")

    wordpress_status = resolve_wordpress_status(decision, draft_first)
    lines.append(
        f"Publication Decision: {decision.recommended_status.value} "
        f"(publish_ready={decision.publish_ready})"
    )
    lines.append(f"  사유: {decision.reason or '(없음)'}")
    lines.append(f"WordPress 예정 status: {wordpress_status if wordpress_status else '(발행하지 않음)'}")

    return "\n".join(lines)
