"""여러 콘텐츠 생성 모듈(wordpress_writer/threads_writer/notebooklm_script/
youtube_meta/thumbnail_prompt)이 공통으로 쓰는 Fact Grounding 로직.

이 패키지는 modules/master_content의 스키마 타입에만 의존한다(다른
modules/* 패키지에 의존하지 않는다). 각 채널 모듈은 이 패키지를 가져다
쓰기만 하고, 채널 간에 서로를 참조하지 않는다.
"""
