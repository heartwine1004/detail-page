"""SRT 자막 파싱/생성 및 ffmpeg(ASS) 스타일 색 변환 유틸."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Cue:
    """자막 한 조각 (시작/끝 초 + 텍스트)."""

    index: int
    start: float
    end: float
    text: str


def _fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_ts(ts: str) -> float:
    ts = ts.strip().replace(".", ",")
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def build_srt(cues: list[Cue]) -> str:
    """Cue 목록을 SRT 문자열로 직렬화."""
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{_fmt_ts(c.start)} --> {_fmt_ts(c.end)}\n{c.text.strip()}\n"
        )
    return "\n".join(blocks)


def parse_srt(text: str) -> list[Cue]:
    """SRT 문자열을 Cue 목록으로 파싱."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if len(lines) < 2:
            continue
        idx_line = 0
        if lines[0].strip().isdigit():
            idx_line = 1
        if "-->" not in lines[idx_line]:
            continue
        start_s, end_s = lines[idx_line].split("-->")
        body = "\n".join(lines[idx_line + 1:])
        cues.append(
            Cue(
                index=len(cues) + 1,
                start=_parse_ts(start_s),
                end=_parse_ts(end_s),
                text=body,
            )
        )
    return cues


def hex_to_ass(color: str, alpha: int = 0) -> str:
    """'#RRGGBB' → ASS 색상 '&HAABBGGRR'. alpha 0=불투명, 255=완전투명."""
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        color = "FFFFFF"
    r, g, b = color[0:2], color[2:4], color[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def force_style(
    font: str = "Malgun Gothic",
    fontsize: int = 22,
    primary: str = "#FFFFFF",
    outline: str = "#000000",
    back: str = "#000000",
    box: bool = True,
) -> str:
    """ffmpeg subtitles 필터의 force_style 문자열 생성.

    box=True 면 반투명 배경 박스(BorderStyle=3), False 면 외곽선만(=1).
    """
    style = {
        "FontName": font,
        "FontSize": fontsize,
        "PrimaryColour": hex_to_ass(primary),
        "OutlineColour": hex_to_ass(outline),
        "BackColour": hex_to_ass(back, alpha=80 if box else 0),
        "BorderStyle": 3 if box else 1,
        "Outline": 2,
        "Shadow": 0,
        "Alignment": 2,  # 하단 가운데
        "MarginV": 30,
    }
    return ",".join(f"{k}={v}" for k, v in style.items())
