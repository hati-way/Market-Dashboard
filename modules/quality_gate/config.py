"""Quality Gate 판정 기준.

모든 임계값은 여기 한 곳에서만 정의한다. 각 score_*.py 는 이 값을
읽기만 하고, 자기 파일 안에 별도의 매직 넘버를 하드코딩하지 않는다.
필요하면 QualityGateConfig(seo_min=90, ...) 처럼 값을 바꿔서 넘기면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityGateConfig:
    # 통과 기준 (0~100점)
    seo_min: int = 80
    aeo_min: int = 80
    geo_min: int = 85
    neo_min: int = 75
    overall_min: int = 82

    # SEO
    title_min_len: int = 10
    title_max_len: int = 70
    slug_max_len: int = 80
    meta_description_min_len: int = 50
    meta_description_max_len: int = 160
    # (키워드 등장 글자수 합) / (전체 글자수). 자연스러운 글도 핵심 키워드를
    # 몇 차례 반복하므로 너무 낮게 잡으면 정상적인 글까지 걸린다.
    max_keyword_repetition_ratio: float = 0.08

    # AEO
    direct_answer_max_len: int = 90

    # NEO
    max_paragraph_length: int = 350  # 이보다 긴 문단은 가독성 경고


DEFAULT_CONFIG = QualityGateConfig()
