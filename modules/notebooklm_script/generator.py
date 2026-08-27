"""7단계: NotebookLM 영상 제작용 원고 생성.

지금은 wordpress 콘텐츠를 그대로 읽어주는 형태의 placeholder 원고를
만든다. TODO: clients/llm_client.py 연동 후 대화체 원고로 교체.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, NotebookLmContent


def generate_notebooklm_script(content: MasterContent) -> MasterContent:
    wp = content.wordpress
    script = (
        f"오늘의 주제는 '{wp.title}' 입니다.\n\n"
        f"{wp.excerpt}\n\n"
        "지금부터 자세한 내용을 살펴보겠습니다."
    )

    content.notebooklm = NotebookLmContent(script=script)
    content.touch()
    return content
