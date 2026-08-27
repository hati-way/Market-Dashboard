"""4단계: SEO/AEO/GEO/NEO 품질 검사 통합 실행기."""
from __future__ import annotations

from datetime import datetime, timezone

from modules.master_content.schema import ContentStatus, MasterContent, QualityCheck

from .aeo_checker import check_aeo
from .geo_checker import check_geo
from .neo_checker import check_neo
from .seo_checker import check_seo


def run_quality_check(content: MasterContent) -> MasterContent:
    """4가지 검사를 모두 실행하고 quality_check 필드를 채운다.

    전부 통과해야 content.meta.status 가 QUALITY_CHECKED 로 바뀐다.
    하나라도 실패하면 QUALITY_FAILED 로 표시되어 5단계(발행)로
    넘어가지 않는다.
    """
    seo = check_seo(content)
    aeo = check_aeo(content)
    geo = check_geo(content)
    neo = check_neo(content)

    overall_passed = all([seo.passed, aeo.passed, geo.passed, neo.passed])

    content.quality_check = QualityCheck(
        seo=seo,
        aeo=aeo,
        geo=geo,
        neo=neo,
        overall_passed=overall_passed,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    content.meta.status = (
        ContentStatus.QUALITY_CHECKED if overall_passed else ContentStatus.QUALITY_FAILED
    )
    content.touch()
    return content
