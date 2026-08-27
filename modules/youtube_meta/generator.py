"""8단계: YouTube 제목/설명/챕터/고정댓글 생성.

지금은 wordpress/notebooklm 콘텐츠를 재활용한 placeholder 구현이다.
TODO: clients/llm_client.py 연동 후 YouTube SEO에 맞게 교체.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, YoutubeChapter, YoutubeMeta


def generate_youtube_meta(content: MasterContent) -> MasterContent:
    wp = content.wordpress

    content.youtube = YoutubeMeta(
        title=wp.title,
        description=wp.excerpt,
        chapters=[YoutubeChapter(timestamp="00:00", title="인트로")],
        pinned_comment=f"오늘의 주제: {wp.title}\n{wp.excerpt}",
        tags=wp.tags,
    )
    content.touch()
    return content
