"""9단계: Midjourney 썸네일 프롬프트 및 Canva 썸네일 문구 생성.

지금은 주제를 영어 프롬프트 템플릿에 끼워 넣는 placeholder 구현이다.
TODO: clients/llm_client.py 연동 후 더 정교한 프롬프트로 교체.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, ThumbnailAssets


def generate_thumbnail_assets(content: MasterContent) -> MasterContent:
    topic = content.meta.topic or content.wordpress.title

    midjourney_prompt = (
        f"finance news thumbnail, topic: {topic}, "
        "bold modern typography, dark blue and neon accent colors, "
        "stock market chart background, high contrast, 16:9 --ar 16:9"
    )
    canva_text = topic

    content.thumbnail = ThumbnailAssets(
        midjourney_prompt=midjourney_prompt,
        canva_text=canva_text,
    )
    content.touch()
    return content
