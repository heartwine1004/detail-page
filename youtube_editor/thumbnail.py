"""썸네일 자동 생성 모듈 (영상 완성 후).

두 가지를 만든다:
  1) 대표 프레임 후보 여러 장 (골라 쓰기용)
  2) 큰 한국어 제목을 얹은 유튜브용 썸네일 1280x720 (바로 업로드용)
모두 ffmpeg 로 처리한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Optional

ProgressCb = Callable[[str], None]


class ThumbnailError(Exception):
    pass


_BOLD_FONTS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _font() -> Optional[str]:
    for p in _BOLD_FONTS:
        if os.path.exists(p):
            return p
    return None


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\u2019").replace("%", "\\%"))


def _probe_duration(video: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", video],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _wrap(title: str, per_line: int = 11) -> str:
    """긴 제목을 대략 per_line 글자 기준 최대 2줄로 접는다(공백 우선)."""
    title = title.strip()
    if len(title) <= per_line:
        return title
    words = title.split()
    if len(words) > 1:
        line1, line2, cur = [], [], 0
        for w in words:
            if cur and cur + len(w) + 1 > per_line and not line2:
                line2.append(w)
            elif line2:
                line2.append(w)
            else:
                line1.append(w)
                cur += len(w) + 1
        return " ".join(line1) + "\n" + " ".join(line2)
    # 공백이 없으면 글자수로 자름
    return title[:per_line] + "\n" + title[per_line:per_line * 2]


def extract_candidates(
    video: str, out_dir: str, count: int = 5, log: ProgressCb = lambda _m: None,
) -> list[str]:
    """영상에서 균등 간격으로 대표 프레임 후보를 뽑아 저장한다(1280x720)."""
    if not shutil.which("ffmpeg"):
        raise ThumbnailError("ffmpeg 가 필요합니다.")
    os.makedirs(out_dir, exist_ok=True)
    dur = _probe_duration(video) or 0
    paths = []
    for i in range(1, count + 1):
        ts = dur * i / (count + 1) if dur else 0
        out = os.path.join(out_dir, f"thumb_cand_{i}.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{ts:.2f}", "-i", video, "-frames:v", "1",
             "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
             out],
            capture_output=True, text=True,
        )
        if os.path.exists(out):
            paths.append(out)
    log(f"대표 프레임 후보 {len(paths)}장 저장")
    return paths


def make_thumbnail(
    video: str,
    output: str,
    title: str = "",
    at: Optional[float] = None,
    accent: str = "#FFE500",
    log: ProgressCb = lambda _m: None,
) -> str:
    """대표 프레임 한 장을 골라 큰 제목을 얹은 유튜브 썸네일을 만든다.

    at: 프레임 뽑을 시각(초). None 이면 ffmpeg thumbnail 필터로 대표 장면 자동 선택.
    """
    if not shutil.which("ffmpeg"):
        raise ThumbnailError("ffmpeg 가 필요합니다.")

    # 1) 베이스 프레임 확보 (1280x720)
    base = os.path.splitext(output)[0] + "_base.jpg"
    scale = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720"
    if at is not None:
        cmd = ["-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", "-vf", scale]
    else:
        # thumbnail 필터로 대표성이 높은 프레임을 자동 선택
        cmd = ["-i", video, "-frames:v", "1", "-vf", f"thumbnail=100,{scale}"]
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *cmd, base],
        capture_output=True, text=True,
    )
    if not os.path.exists(base):
        raise ThumbnailError("베이스 프레임을 뽑지 못했습니다.")

    # 2) 가독성용 하단 어둡게 깔기 + 제목 텍스트
    filters = [
        "drawbox=x=0:y=460:w=1280:h=260:color=black@0.45:t=fill",
    ]
    if title.strip():
        font = _font()
        if font:
            wrapped = _wrap(title)
            filters.append(
                f"drawtext=fontfile='{_esc(font)}':text='{_esc(wrapped)}'"
                f":fontcolor=white:fontsize=88:line_spacing=12"
                f":borderw=6:bordercolor=black"
                f":box=0:x=(w-text_w)/2:y=h-text_h-60"
            )
            # 상단 좌측 악센트 바
            filters.insert(0,
                           f"drawbox=x=0:y=0:w=16:h=720:color={accent.replace('#','0x')}:t=fill")
        else:
            log("  · 한글 폰트를 못 찾아 제목 없이 이미지만 생성합니다.")

    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", base, "-vf", ",".join(filters), "-frames:v", "1", output],
        capture_output=True, text=True, check=False,
    )
    try:
        os.remove(base)
    except OSError:
        pass
    if not os.path.exists(output):
        raise ThumbnailError("썸네일 생성에 실패했습니다.")
    log(f"썸네일 완성 → {output}")
    return output
