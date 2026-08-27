"""Quality Gate: WordPressArticle 발행 전 최종 검사.

fire-your-seo-agency 스킬(.claude/skills/fire-your-seo-agency/)에서
참고한 SEO/AEO/GEO/NEO 원칙을 우리 MasterContent/WordPressArticle/
Fact Grounding 구조에 맞게 다시 구현했다. 어떤 원칙을 가져오고
어떤 것을 가져오지 않았는지는
.claude/skills/fire-your-seo-agency/PROJECT_NOTES.md 에 정리되어 있다.

핵심 규칙: Fact Validation 결과가 SEO/AEO/GEO/NEO 점수보다 항상
우선한다. 점수가 아무리 높아도 Fact가 FAIL이면 전체 결과는 FAIL이다.

이 모듈은 검사만 한다 — WordPressArticle 본문을 수정하지 않는다.
"""
from .config import DEFAULT_CONFIG, QualityGateConfig
from .gate import decide_publication, run_quality_gate, run_quality_gate_for_content
from .models import (
    GateStatus,
    LaneScore,
    PublicationDecision,
    QualityGateResult,
    RecommendedStatus,
    ScoreBreakdown,
)

__all__ = [
    "run_quality_gate",
    "run_quality_gate_for_content",
    "decide_publication",
    "QualityGateConfig",
    "DEFAULT_CONFIG",
    "GateStatus",
    "LaneScore",
    "ScoreBreakdown",
    "QualityGateResult",
    "RecommendedStatus",
    "PublicationDecision",
]
