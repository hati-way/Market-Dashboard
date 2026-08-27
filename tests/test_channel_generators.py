"""6~9단계 각 채널 생성 모듈이 서로 독립적으로 동작하는지 확인한다."""
from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content
from modules.notebooklm_script.generator import generate_notebooklm_script
from modules.thumbnail_prompt.generator import generate_thumbnail_assets
from modules.threads_writer.generator import generate_threads_content
from modules.wordpress_writer.generator import generate_wordpress_content
from modules.youtube_meta.generator import generate_youtube_meta

SAMPLE_INPUT = "data/input/sample_market_data.json"


def _content_with_wordpress():
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="미국 증시 브리핑", market_data=market_data)
    return generate_wordpress_content(content)


def test_threads_writer_independent():
    content = generate_threads_content(_content_with_wordpress())
    assert content.threads.posts
    assert content.threads.posts[0].text


def test_notebooklm_script_independent():
    content = generate_notebooklm_script(_content_with_wordpress())
    assert content.notebooklm.script


def test_youtube_meta_independent():
    content = generate_youtube_meta(_content_with_wordpress())
    assert content.youtube.title
    assert content.youtube.chapters


def test_thumbnail_prompt_independent():
    content = generate_thumbnail_assets(_content_with_wordpress())
    assert content.thumbnail.midjourney_prompt
    assert content.thumbnail.canva_text
