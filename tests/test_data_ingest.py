"""modules/data_ingest/ingest.py 의 load_market_content_input_from_json_file() 테스트.

기존(flat) 형식과, topic/market_data/analysis 를 함께 담은 확장 형식을
둘 다 올바르게 읽는지 확인한다.
"""
import json

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.schema import ConfidenceLevel, SourceType

FLAT_SAMPLE = "data/input/sample_market_data.json"
EXTENDED_SAMPLE = "data/input/sample_treasury_buyback.json"


def test_flat_format_returns_no_topic_and_empty_analysis():
    result = load_market_content_input_from_json_file(FLAT_SAMPLE)

    assert result.topic is None
    assert result.market_data.as_of_date == "2026-08-26"
    assert result.analysis.facts == []
    assert result.analysis.sources == []


def test_extended_format_returns_topic_market_data_and_analysis():
    result = load_market_content_input_from_json_file(EXTENDED_SAMPLE)

    assert result.topic == "미국 재무부 바이백이 금융시장에 미치는 영향"
    assert result.market_data.as_of_date == "2026-08-27"
    assert len(result.analysis.facts) == 4
    assert len(result.analysis.sources) == 2

    fact_by_id = {fact.id: fact for fact in result.analysis.facts}
    assert fact_by_id["fact_001"].value == 300
    assert fact_by_id["fact_002"].value == 4.05
    assert fact_by_id["fact_002"].source_type == SourceType.PRIMARY
    assert fact_by_id["fact_004"].confidence == ConfidenceLevel.LOW


def test_extended_format_with_only_market_data_key(tmp_path):
    path = tmp_path / "only_market_data.json"
    path.write_text(
        json.dumps({"market_data": {"as_of_date": "2026-01-01", "indices": []}}),
        encoding="utf-8",
    )

    result = load_market_content_input_from_json_file(path)

    assert result.topic is None
    assert result.market_data.as_of_date == "2026-01-01"
    assert result.analysis.facts == []


def test_extended_format_with_only_analysis_key(tmp_path):
    path = tmp_path / "only_analysis.json"
    path.write_text(
        json.dumps({"analysis": {"primary_question": "테스트 질문"}}),
        encoding="utf-8",
    )

    result = load_market_content_input_from_json_file(path)

    assert result.topic is None
    assert result.market_data.as_of_date == ""
    assert result.analysis.primary_question == "테스트 질문"
