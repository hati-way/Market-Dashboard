"""Quality Gate 결과 모델.

fire-your-seo-agency 스킬(.claude/skills/fire-your-seo-agency/)에서
참고한 SEO/AEO/GEO/NEO 원칙을, 우리 MasterContent/WordPressArticle/
Fact Grounding 구조에서 검사 가능한 형태로 다시 짠 결과다. 자세한
내용은 modules/quality_gate/__init__.py 와
.claude/skills/fire-your-seo-agency/PROJECT_NOTES.md 를 참고.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from modules.wordpress_writer.fact_validation import FactValidationStatus

# Quality Gate의 전체 상태도 Fact Validation과 같은 3단계
# (PASS/REVIEW_REQUIRED/FAIL)를 쓴다. 의미가 같으므로 별도 Enum을
# 새로 만들지 않고 그대로 재사용한다.
GateStatus = FactValidationStatus


class LaneScore(BaseModel):
    """SEO/AEO/GEO/NEO 각 레인 하나의 점수와 근거."""

    score: int
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    fact: int
    seo: int
    aeo: int
    geo: int
    neo: int
    overall: int


class QualityGateResult(BaseModel):
    status: GateStatus
    scores: ScoreBreakdown
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # recommendations는 자동 수정이 아니라 사람이 검토할 개선 제안이다.
    recommendations: list[str] = Field(default_factory=list)


class RecommendedStatus(str, Enum):
    PUBLISH = "publish"
    DRAFT = "draft"
    BLOCKED = "blocked"


class PublicationDecision(BaseModel):
    """WordPress 발행 여부를 결정하는 모델.

    실제 WordPress API 발행(modules/wordpress_publisher)은 아직 구현하지
    않았다. 이 모델은 나중에 publisher가 그대로 가져다 쓸 수 있는
    "발행해도 되는가"의 최종 판단만 담는다.
    """

    publish_ready: bool
    recommended_status: RecommendedStatus
    reason: str = ""
