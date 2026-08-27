from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content
from modules.quality_check.checker import run_quality_check
from modules.wordpress_writer.generator import generate_wordpress_content

SAMPLE_INPUT = "data/input/sample_market_data.json"


def _build_generated_content(fake_llm_client):
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="미국 증시 브리핑", market_data=market_data)
    return generate_wordpress_content(content, llm_client=fake_llm_client)


def test_quality_check_fails_on_empty_content():
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="빈 콘텐츠", market_data=market_data)
    # wordpress 필드를 채우지 않은 상태로 바로 검사
    content = run_quality_check(content)

    assert content.quality_check.overall_passed is False
    assert content.quality_check.seo.issues


def test_quality_check_runs_all_four_checks(fake_llm_client):
    content = _build_generated_content(fake_llm_client)
    content = run_quality_check(content)

    assert content.quality_check.seo is not None
    assert content.quality_check.aeo is not None
    assert content.quality_check.geo is not None
    assert content.quality_check.neo is not None
    assert content.quality_check.checked_at is not None
