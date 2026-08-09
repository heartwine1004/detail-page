"""한국어 대본 자동 생성 모듈 (자동편집기 3단계 자동화).

원어 자막(음성인식 결과)을 Claude API 에 보내 한국어 유튜브 나레이션 대본을
받아온다. 이걸 쓰면 클로드에 수동으로 붙여넣던 단계가 앱 안에서 자동 처리된다.

Anthropic 공식 SDK(`anthropic`) 사용. 긴 출력이므로 스트리밍으로 받는다.
API 키는 환경변수 ANTHROPIC_API_KEY 또는 생성자 인자로 전달.
"""

from __future__ import annotations

from typing import Callable, Optional

from . import script_tools

ProgressCb = Callable[[str], None]

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
당신은 한국어 유튜브 나레이션 대본 작가입니다. 외국 영상의 원어 자막을 받아
그 내용을 바탕으로 한국어 나레이션 대본을 씁니다.

작성 원칙:
- 원본의 사실과 흐름을 유지하되, 자연스러운 한국어 구어체로 재구성한다.
- 도입부(첫 2~3문장)는 시청자를 붙잡는 훅으로 시작한다.
- 한 문장씩 줄바꿈한다(TTS·자막 싱크용). 한 문장은 너무 길지 않게.
- 군더더기·중복·의미 없는 추임새는 정리한다.
- 최종 출력은 대본 본문만. 머리말('아래는...'), 번호, 마크다운, 설명은 넣지 않는다.
"""


class ScriptGenError(Exception):
    pass


def _client(api_key: Optional[str]):
    try:
        import anthropic
    except ImportError as exc:
        raise ScriptGenError(
            "anthropic 패키지가 필요합니다. `pip install anthropic`"
        ) from exc
    # api_key 를 주면 그걸 쓰고, 없으면 SDK 가 환경변수/프로필에서 해결한다.
    try:
        return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    except Exception as exc:  # noqa: BLE001
        raise ScriptGenError(f"Anthropic 클라이언트 생성 실패: {exc}") from exc


def generate_korean_script(
    transcript_text: str,
    title: str = "",
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    log: ProgressCb = lambda _m: None,
) -> str:
    """원어 자막 → 한국어 나레이션 대본. 스트리밍으로 받아 전체 텍스트를 반환."""
    if not transcript_text.strip():
        raise ScriptGenError("원어 자막이 비어 있습니다. 먼저 2단계를 완료하세요.")

    client = _client(api_key)

    user_content = ""
    if title:
        user_content += f"[영상 제목] {title}\n\n"
    user_content += "[원어 자막]\n" + transcript_text.strip()

    log(f"대본 생성 중... (모델: {model})")
    try:
        # 긴 출력이므로 스트리밍 + get_final_message 사용 (SDK 타임아웃 회피).
        with client.messages.stream(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            final = stream.get_final_message()
    except Exception as exc:  # noqa: BLE001
        # anthropic.* 예외를 포함해 사용자 친화적으로 감싼다.
        raise ScriptGenError(f"대본 생성 실패: {exc}") from exc

    if getattr(final, "stop_reason", None) == "refusal":
        raise ScriptGenError("모델이 요청을 거절했습니다(refusal). 다른 영상으로 시도하세요.")

    text = "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
    if not text.strip():
        raise ScriptGenError("빈 대본이 반환되었습니다.")

    # Vrew·TTS 에 바로 넣을 수 있도록 문장 단위로 정리해 반환.
    return script_tools.format_for_vrew(text)
