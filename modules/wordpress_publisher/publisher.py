"""5단계: 품질 검사를 통과한 콘텐츠만 WordPress에 발행.

주의: 이번 단계에서는 아직 실제 WordPress REST API 연동을 구현하지
않는다 (프로젝트 뼈대 작업 범위 밖). clients/wordpress_client.py 에
실제 REST API 호출 코드가 채워지면, 아래 publish_to_wordpress() 안에서
그 클라이언트를 호출하도록 교체한다.

인터페이스(MasterContent 를 받아 MasterContent 를 반환)는 지금부터
고정해 두어, 나중에 내부 구현만 바꿔도 orchestrator.py 를 수정할
필요가 없도록 한다.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, PublishResult


class NotReadyToPublishError(Exception):
    """품질 검사를 통과하지 못한 콘텐츠를 발행하려고 할 때 발생."""


def publish_to_wordpress(content: MasterContent) -> MasterContent:
    if not content.quality_check.overall_passed:
        raise NotReadyToPublishError(
            "품질 검사를 통과하지 못한 콘텐츠는 발행할 수 없습니다. "
            "quality_check.overall_passed 를 확인하세요."
        )

    # TODO: clients/wordpress_client.py 의 실제 REST API 클라이언트로 교체.
    content.publish = PublishResult(published=False, post_id=None, post_url=None, published_at=None)
    content.touch()
    raise NotImplementedError(
        "WordPress 발행 기능은 아직 구현되지 않았습니다. "
        "clients/wordpress_client.py 를 구현한 뒤 이 함수를 완성하세요."
    )
