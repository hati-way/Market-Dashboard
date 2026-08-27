"""MasterContent.analysis (Fact/Source/Analysis) 검증 테스트.

작업 지시에 명시된 6가지 시나리오를 각각 확인한다.
"""
import pytest
from pydantic import ValidationError

from modules.master_content.schema import (
    Analysis,
    ConfidenceLevel,
    Fact,
    MasterContent,
    Source,
    SourceType,
)


def _valid_fact_kwargs() -> dict:
    return dict(
        claim="미국 근원 PCE 물가지수가 예상치를 하회했다.",
        value=2.6,
        unit="%",
        date="2026-08-26",
        source="U.S. Bureau of Economic Analysis",
        source_type="primary",
        confidence="high",
    )


# 1. 필수 정보 누락 (claim 누락)
def test_fact_missing_claim_raises_validation_error():
    kwargs = _valid_fact_kwargs()
    del kwargs["claim"]
    with pytest.raises(ValidationError):
        Fact(**kwargs)


# 2. 잘못된 confidence
def test_fact_invalid_confidence_raises_validation_error():
    kwargs = _valid_fact_kwargs()
    kwargs["confidence"] = "very_high"  # high/medium/low 가 아님
    with pytest.raises(ValidationError):
        Fact(**kwargs)


def test_analysis_invalid_confidence_raises_validation_error():
    with pytest.raises(ValidationError):
        Analysis(confidence="super")


# 3. 잘못된 source_type
def test_fact_invalid_source_type_raises_validation_error():
    kwargs = _valid_fact_kwargs()
    kwargs["source_type"] = "official"  # primary/secondary/unknown 이 아님
    with pytest.raises(ValidationError):
        Fact(**kwargs)


# 4. 날짜 형식 오류
def test_fact_invalid_date_format_raises_validation_error():
    kwargs = _valid_fact_kwargs()
    kwargs["date"] = "2026/08/26"  # ISO(YYYY-MM-DD) 형식이 아님
    with pytest.raises(ValidationError):
        Fact(**kwargs)


def test_fact_nonsense_date_raises_validation_error():
    kwargs = _valid_fact_kwargs()
    kwargs["date"] = "not-a-date"
    with pytest.raises(ValidationError):
        Fact(**kwargs)


# 5. source가 없는 핵심 fact
def test_fact_missing_source_raises_validation_error():
    kwargs = _valid_fact_kwargs()
    del kwargs["source"]
    with pytest.raises(ValidationError):
        Fact(**kwargs)


# 6. 정상적인 전체 MasterContent
def test_full_master_content_with_analysis_is_valid():
    fact = Fact(**_valid_fact_kwargs())
    source = Source(
        name="U.S. Bureau of Economic Analysis",
        url="https://www.bea.gov/",
        source_type=SourceType.PRIMARY,
    )
    analysis = Analysis(
        primary_question="이번 PCE 발표가 연준의 금리 인하 속도에 어떤 영향을 주는가?",
        summary="근원 PCE가 예상치를 하회하며 인하 기대가 강화되었다.",
        facts=[fact],
        sources=[source],
        causal_chain=["PCE 둔화", "인플레이션 우려 완화", "인하 기대 강화"],
        market_implications=["단기 국채 금리 하락 압력"],
        bull_case=["인하 사이클 조기 시작 가능성"],
        bear_case=["고용지표가 반대로 강하게 나올 경우 되돌림 가능"],
        risks=["차기 고용지표 서프라이즈"],
        invalidating_conditions=["근원 PCE 재상승 전환"],
        update_triggers=["다음 FOMC 회의", "다음 PCE 발표일"],
        confidence=ConfidenceLevel.MEDIUM,
    )

    content = MasterContent()
    content.meta.topic = "미국 근원 PCE와 금리 인하 경로"
    content.market_data.as_of_date = "2026-08-26"
    content.analysis = analysis

    assert content.analysis.primary_question
    assert content.analysis.facts[0].claim == fact.claim
    assert content.analysis.facts[0].source_type == SourceType.PRIMARY
    assert content.analysis.confidence == ConfidenceLevel.MEDIUM

    # 라운드트립 (직렬화 -> 역직렬화) 에서도 값이 그대로 유지되는지 확인
    dumped = content.model_dump(mode="json")
    restored = MasterContent.model_validate(dumped)
    assert restored.analysis.facts[0].claim == fact.claim
    assert str(restored.analysis.facts[0].date) == "2026-08-26"


def test_master_content_default_analysis_still_constructs_without_args():
    """기존 코드(MasterContent() 인자 없이 생성)가 계속 동작하는지 확인하는 회귀 테스트."""
    content = MasterContent()
    assert content.analysis == Analysis()
    assert content.analysis.facts == []
    assert content.analysis.confidence == ConfidenceLevel.MEDIUM
