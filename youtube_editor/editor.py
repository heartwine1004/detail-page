"""영상 편집 모듈 (ffmpeg 래퍼).

내려받은 영상 파일에 대해 자르기 / 화질·포맷 변환 / 오디오 추출 / 속도 조절을
수행한다. 모든 작업은 ffmpeg 를 subprocess 로 호출한다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional


class EditorError(Exception):
    """편집 중 발생한 오류."""


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise EditorError(
            f"'{binary}' 를 찾을 수 없습니다. ffmpeg 를 설치하세요 "
            "(예: `apt-get install ffmpeg` 또는 https://ffmpeg.org)."
        )
    return path


def parse_time(value: str | float | int) -> float:
    """'1:23', '01:02:03', '90', 90 등 다양한 표기를 초(float)로 변환."""
    if isinstance(value, (int, float)):
        return float(value)
    value = value.strip()
    if not value:
        raise EditorError("시간 값이 비어 있습니다.")
    parts = value.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError as exc:
        raise EditorError(f"시간 형식을 해석할 수 없습니다: {value!r}") from exc
    seconds = 0.0
    for p in parts:  # [h,m,s] / [m,s] / [s]
        seconds = seconds * 60 + p
    return seconds


class Editor:
    """ffmpeg 기반 영상 편집기."""

    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.ffmpeg = _require("ffmpeg")
        self.ffprobe = shutil.which("ffprobe") or ""

    # ------------------------------------------------------------------ util
    def _run(self, args: list[str]) -> None:
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise EditorError(
                "ffmpeg 실행 실패:\n" + (proc.stderr.strip() or "알 수 없는 오류")
            )

    def _out(self, src: str, suffix: str, ext: Optional[str] = None) -> str:
        base = os.path.splitext(os.path.basename(src))[0]
        ext = ext or os.path.splitext(src)[1].lstrip(".") or "mp4"
        return os.path.join(self.output_dir, f"{base}_{suffix}.{ext}")

    def probe_duration(self, src: str) -> Optional[float]:
        """영상 길이(초)를 반환. ffprobe 없으면 None."""
        if not self.ffprobe:
            return None
        cmd = [
            self.ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "json", src,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        try:
            return float(json.loads(proc.stdout)["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------ trim
    def trim(
        self,
        src: str,
        start: str | float,
        end: str | float,
        output: Optional[str] = None,
        fast: bool = False,
    ) -> str:
        """start ~ end 구간만 잘라낸다.

        fast=True 는 재인코딩 없이(스트림 복사) 빠르지만 키프레임 단위로만 정확.
        fast=False 는 재인코딩하여 프레임 단위로 정확(기본값).
        """
        s = parse_time(start)
        e = parse_time(end)
        if e <= s:
            raise EditorError("끝 시간이 시작 시간보다 뒤여야 합니다.")
        out = output or self._out(src, "trim")
        if fast:
            args = ["-ss", str(s), "-to", str(e), "-i", src, "-c", "copy", out]
        else:
            args = [
                "-i", src, "-ss", str(s), "-to", str(e),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", out,
            ]
        self._run(args)
        return out

    # --------------------------------------------------------------- convert
    def convert(
        self,
        src: str,
        output: Optional[str] = None,
        height: Optional[int] = None,
        fmt: str = "mp4",
    ) -> str:
        """화질(세로 픽셀) / 컨테이너 포맷 변환. 예: height=720, fmt='mp4'."""
        out = output or self._out(src, f"{height or 'src'}p", ext=fmt)
        args = ["-i", src]
        if height:
            # 가로는 비율 유지, 짝수 보정
            args += ["-vf", f"scale=-2:{height}"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-c:a", "aac", out]
        self._run(args)
        return out

    # ---------------------------------------------------------- extract audio
    def extract_audio(
        self,
        src: str,
        output: Optional[str] = None,
        fmt: str = "mp3",
        bitrate: str = "192k",
    ) -> str:
        """영상에서 오디오만 추출. fmt: mp3 / wav / m4a / aac."""
        out = output or self._out(src, "audio", ext=fmt)
        codec = {
            "mp3": "libmp3lame",
            "wav": "pcm_s16le",
            "m4a": "aac",
            "aac": "aac",
        }.get(fmt, "libmp3lame")
        args = ["-i", src, "-vn", "-acodec", codec]
        if fmt != "wav":
            args += ["-b:a", bitrate]
        args += [out]
        self._run(args)
        return out

    # ----------------------------------------------------------------- speed
    def change_speed(
        self, src: str, factor: float, output: Optional[str] = None
    ) -> str:
        """재생 속도 변경. factor=2.0 → 2배속, 0.5 → 절반 속도."""
        if factor <= 0:
            raise EditorError("속도 배수는 0보다 커야 합니다.")
        out = output or self._out(src, f"{factor}x")
        # 오디오 atempo 는 0.5~2.0 범위만 지원 → 여러 단계로 분해
        atempo = self._atempo_chain(factor)
        args = [
            "-i", src,
            "-filter_complex",
            f"[0:v]setpts={1/factor}*PTS[v];[0:a]{atempo}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            out,
        ]
        self._run(args)
        return out

    @staticmethod
    def _atempo_chain(factor: float) -> str:
        chain = []
        remaining = factor
        while remaining > 2.0:
            chain.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            chain.append("atempo=0.5")
            remaining /= 0.5
        chain.append(f"atempo={remaining:.6f}")
        return ",".join(chain)
