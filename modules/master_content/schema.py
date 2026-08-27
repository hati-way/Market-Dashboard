"""Master Content JSON 스키마.

이 프로젝트의 모든 모듈은 이 하나의 구조(MasterContent)를 입력받거나
채워 넣는 방식으로 동작한다. 즉 데이터 흐름은 다음과 같다.

    market_data 입력
        -> MasterContent 생성 (market_data 채움)
        -> analysis 채움 (primary_question/summary/facts/sources 등,
           WordPress/Threads/NotebookLM/YouTube 콘텐츠가 공통으로 참조하는
           단일 분석 원본)
        -> wordpress_writer 가 wordpress 필드를 채움
        -> quality_check 가 quality_check 필드를 채움
        -> (통과 시) wordpress_publisher 가 발행 후 published 필드를 채움
        -> threads_writer / notebooklm_script / youtube_meta / thumbnail_prompt
           가 각자의 필드를 채움
        -> performance_tracker 가 performance 필드를 채움

각 단계는 MasterContent 를 받아서 특정 필드만 채운 MasterContent 를
반환하는 형태로 통일한다. 그래야 모듈을 독립적으로 테스트할 수 있다.
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContentStatus(str, Enum):
    DRAFT = "draft"                # 생성만 된 상태
    QUALITY_CHECKED = "quality_checked"  # 품질 검사 통과
    QUALITY_FAILED = "quality_failed"    # 품질 검사 미통과
    PUBLISHED = "published"        # WordPress 발행 완료


class SourceType(str, Enum):
    PRIMARY = "primary"      # 1차 출처 (공식 발표, 원자료 등)
    SECONDARY = "secondary"  # 2차 출처 (기사, 리포트 등 1차 출처를 인용/가공한 자료)
    UNKNOWN = "unknown"      # 출처 신뢰도를 아직 분류하지 않음


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Meta(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str = ""
    language: str = "ko"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    status: ContentStatus = ContentStatus.DRAFT


class MarketDataPoint(BaseModel):
    """지수/환율/원자재 등 단일 시세 항목."""

    name: str
    value: float
    change_percent: float | None = None
    unit: str | None = None


class MacroEvent(BaseModel):
    """거시경제 이벤트/지표 발표."""

    name: str
    date: str
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    importance: str | None = None  # e.g. "high" / "medium" / "low"


class MarketData(BaseModel):
    """1단계: 입력받은 원본 금융/거시경제 데이터."""

    as_of_date: str = ""
    indices: list[MarketDataPoint] = Field(default_factory=list)
    fx: list[MarketDataPoint] = Field(default_factory=list)
    commodities: list[MarketDataPoint] = Field(default_factory=list)
    macro_events: list[MacroEvent] = Field(default_factory=list)
    notes: str = ""
    raw_source: dict[str, Any] = Field(default_factory=dict)


class Fact(BaseModel):
    """분석의 근거가 되는 개별 사실/수치.

    모든 fact는 근거(source)가 있는 핵심 사실로 취급한다. 따라서 claim과
    source는 필수값이며, source_type/confidence 는 정해진 값(Enum)만
    허용한다.
    """

    claim: str
    value: str | float | None = None
    unit: str | None = None
    date: date_type | None = None
    source: str
    source_type: SourceType = SourceType.UNKNOWN
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class Source(BaseModel):
    """분석 전반에서 참조한 출처."""

    name: str
    url: str | None = None
    source_type: SourceType = SourceType.UNKNOWN


class Analysis(BaseModel):
    """2단계: WordPress/Threads/NotebookLM/YouTube 콘텐츠가 공유하는
    분석의 원본(단일 출처). market_data(원본 시세/이벤트)를 근거로
    사람 또는 LLM이 정리한 해석 결과를 담는다.
    """

    primary_question: str = ""
    summary: str = ""
    facts: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    causal_chain: list[str] = Field(default_factory=list)
    market_implications: list[str] = Field(default_factory=list)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidating_conditions: list[str] = Field(default_factory=list)
    update_triggers: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class SeoMeta(BaseModel):
    meta_title: str = ""
    meta_description: str = ""
    focus_keyword: str = ""


class WordPressContent(BaseModel):
    """3단계: WordPress 분석글."""

    title: str = ""
    slug: str = ""
    excerpt: str = ""
    content_html: str = ""
    content_markdown: str = ""
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    source_list: list[str] = Field(default_factory=list)
    seo: SeoMeta = Field(default_factory=SeoMeta)


class QualityCheckResult(BaseModel):
    passed: bool = False
    score: float | None = None
    issues: list[str] = Field(default_factory=list)


class QualityCheck(BaseModel):
    """4단계: SEO / AEO / GEO / NEO 품질 검사 결과."""

    seo: QualityCheckResult = Field(default_factory=QualityCheckResult)
    aeo: QualityCheckResult = Field(default_factory=QualityCheckResult)
    geo: QualityCheckResult = Field(default_factory=QualityCheckResult)
    neo: QualityCheckResult = Field(default_factory=QualityCheckResult)
    overall_passed: bool = False
    checked_at: str | None = None


class PublishResult(BaseModel):
    """5단계: WordPress 발행 결과."""

    published: bool = False
    post_id: int | None = None
    post_url: str | None = None
    published_at: str | None = None


class ThreadsPost(BaseModel):
    text: str = ""
    order: int = 0


class ThreadsContent(BaseModel):
    """6단계: Threads 글."""

    posts: list[ThreadsPost] = Field(default_factory=list)


class NotebookLmContent(BaseModel):
    """7단계: NotebookLM 영상 제작용 원고."""

    script: str = ""


class YoutubeChapter(BaseModel):
    timestamp: str
    title: str


class YoutubeMeta(BaseModel):
    """8단계: YouTube 메타데이터."""

    title: str = ""
    description: str = ""
    chapters: list[YoutubeChapter] = Field(default_factory=list)
    pinned_comment: str = ""
    tags: list[str] = Field(default_factory=list)


class ThumbnailAssets(BaseModel):
    """9단계: 썸네일용 프롬프트/문구."""

    midjourney_prompt: str = ""
    canva_text: str = ""


class PerformanceRecord(BaseModel):
    """10단계: 성과 데이터 (Search Console 등)."""

    recorded_at: str
    source: str  # e.g. "search_console", "wordpress"
    metrics: dict[str, Any] = Field(default_factory=dict)


class MasterContent(BaseModel):
    """전체 파이프라인이 공유하는 단일 진실 소스(Single Source of Truth)."""

    meta: Meta = Field(default_factory=Meta)
    market_data: MarketData = Field(default_factory=MarketData)
    analysis: Analysis = Field(default_factory=Analysis)
    wordpress: WordPressContent = Field(default_factory=WordPressContent)
    quality_check: QualityCheck = Field(default_factory=QualityCheck)
    publish: PublishResult = Field(default_factory=PublishResult)
    threads: ThreadsContent = Field(default_factory=ThreadsContent)
    notebooklm: NotebookLmContent = Field(default_factory=NotebookLmContent)
    youtube: YoutubeMeta = Field(default_factory=YoutubeMeta)
    thumbnail: ThumbnailAssets = Field(default_factory=ThumbnailAssets)
    performance: list[PerformanceRecord] = Field(default_factory=list)

    def touch(self) -> None:
        """updated_at 갱신. 각 모듈이 필드를 채운 뒤 호출한다."""
        self.meta.updated_at = _now_iso()
