"""대본 스크립트 유틸 (자동편집기 3·4단계).

3단계: 원어 자막 → Claude(대본생성기)에 붙여넣을 프롬프트 만들기.
4단계: 받은 한국어 대본 → Vrew 에 붙여넣을 음성용 대본(한 줄=한 문장)으로 정리.
"""

from __future__ import annotations

import re

CLAUDE_PROMPT_HEADER = """\
아래는 유튜브 영상의 원어 자막(음성인식 결과)입니다.
이걸 바탕으로 한국어 유튜브 나레이션 대본을 만들어 주세요.

[요청 사항]
- 원본 내용과 사실을 유지하되, 자연스러운 구어체 한국어로 재구성
- 한 문장씩 줄바꿈 (TTS/자막 싱크용)
- 군더더기·중복 표현 정리, 도입부는 시청자를 붙잡는 훅으로
- 최종 출력은 대본 본문만 (설명/머리말 없이)

[원어 자막]
"""


def build_claude_prompt(transcript_text: str, title: str = "") -> str:
    """3단계: 원어 자막을 Claude 대본생성기용 프롬프트로 감싼다."""
    head = CLAUDE_PROMPT_HEADER
    if title:
        head = head.replace("[원어 자막]", f"[영상 제목] {title}\n\n[원어 자막]")
    return head + transcript_text.strip() + "\n"


def format_for_vrew(script_text: str) -> str:
    """4단계: Claude 가 준 대본을 Vrew 붙여넣기용으로 정리한다.

    - 마크다운/머리표/번호 제거
    - 문장 단위로 줄바꿈 (마침표·물음표·느낌표 기준)
    - 빈 줄 정리
    """
    text = script_text.strip()

    # 코드펜스/마크다운 강조 제거
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"[*_`#>]+", "", text)

    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        # 머리표/번호 제거:  "- ", "1. ", "• "
        line = re.sub(r"^\s*(?:[-•·]|\d+[.)])\s*", "", line)
        # 한 줄 안에 여러 문장이 있으면 분리
        parts = re.split(r"(?<=[.!?。！？])\s+", line)
        for p in parts:
            p = p.strip()
            if p:
                lines.append(p)

    return "\n".join(lines)
