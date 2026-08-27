"""6단계: 같은 Master JSON을 이용해 Threads 글 생성.

지금은 wordpress.excerpt 를 재활용한 placeholder 구현이다.
TODO: clients/llm_client.py 연동 후 Threads 톤에 맞는 짧은 글로 교체.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, ThreadsContent, ThreadsPost

THREADS_MAX_LENGTH = 500


def generate_threads_content(content: MasterContent) -> MasterContent:
    summary = content.wordpress.excerpt or content.wordpress.title
    text = summary[:THREADS_MAX_LENGTH]

    content.threads = ThreadsContent(posts=[ThreadsPost(text=text, order=1)])
    content.touch()
    return content
