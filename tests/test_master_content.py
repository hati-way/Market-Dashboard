from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content, load_master_content, save_master_content

SAMPLE_INPUT = "data/input/sample_market_data.json"


def test_build_master_content_from_sample():
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="테스트 주제", market_data=market_data)

    assert content.meta.topic == "테스트 주제"
    assert content.market_data.as_of_date == "2026-08-26"
    assert len(content.market_data.indices) == 2


def test_save_and_load_master_content(tmp_path):
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="저장 테스트", market_data=market_data)

    saved_path = save_master_content(content, directory=tmp_path)
    assert saved_path.exists()

    loaded = load_master_content(saved_path)
    assert loaded.meta.id == content.meta.id
    assert loaded.meta.topic == "저장 테스트"
