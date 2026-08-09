"""영상 합성 모듈 (자동편집기 6단계 '영상 만들기').

원본 영상 위에:
  - Vrew 로 만든 한국어 음성(wav)을 나레이션으로 입히고
  - 한국어 자막(srt)을 스타일 적용해 태우고(burn-in)
  - 출처 표시(워터마크)를 얹고
  - (선택) 원본 BGM 제거
최종 mp4 를 만든다.

오디오 모드(audio_mode):
  - "replace" : 나레이션(한국어 TTS)만 사용, 원본 소리 제거
  - "ambience": 나레이션 + 원본 소리를 낮게 깔기
  - "dub"     : 나레이션이 기본, 지정한 '원음 구간'에서는 원본 인물 목소리가
                나오고 나레이션은 잠깐 줄어듦 (부분 더빙)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import srt_utils

ProgressCb = Callable[[str], None]
TimeRange = tuple[float, float]


class AssembleError(Exception):
    pass


@dataclass
class SubStyle:
    font: str = "Malgun Gothic"
    fontsize: int = 22
    primary: str = "#FFFFFF"
    outline: str = "#000000"
    back: str = "#000000"
    box: bool = True


@dataclass
class SourceMark:
    """출처 표시(워터마크)."""

    text: str = ""              # 비우면 표시 안 함
    position: str = "top-left"  # top-left / top-right / bottom-left / bottom-right
    color: str = "#FFFFFF"
    box_color: str = "#000000"
    fontsize: int = 18


@dataclass
class AssembleOptions:
    subtitle: SubStyle = field(default_factory=SubStyle)
    source: SourceMark = field(default_factory=SourceMark)

    audio_mode: str = "replace"          # replace / ambience / dub
    ambience_volume: float = 0.12        # ambience 모드에서 원본 볼륨
    narration_duck: float = 0.06         # dub 모드에서 원음 구간 나레이션 볼륨
    original_segments: list[TimeRange] = field(default_factory=list)  # 원음 유지 구간(초)
    remove_original_bgm: bool = False    # 원음/앰비언스에서 음악 제거 시도(demucs)


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _find_font() -> Optional[str]:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _esc_sub_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _esc_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "\\%")
    )


def _seg_expr(segments: list[TimeRange]) -> str:
    """원음 구간 → ffmpeg volume 표현식용 'between(t,s,e)+...' (없으면 '0')."""
    parts = [f"between(t,{s:.3f},{e:.3f})" for s, e in segments if e > s]
    return "+".join(parts) if parts else "0"


def _drawtext(mark: SourceMark) -> Optional[str]:
    if not mark.text.strip():
        return None
    font = _find_font()
    if not font:
        return None
    pad = 20
    x, y = {
        "top-left": (f"{pad}", f"{pad}"),
        "top-right": (f"w-tw-{pad}", f"{pad}"),
        "bottom-left": (f"{pad}", f"h-th-{pad}"),
        "bottom-right": (f"w-tw-{pad}", f"h-th-{pad}"),
    }.get(mark.position, (f"{pad}", f"{pad}"))
    return (
        f"drawtext=fontfile='{_esc_sub_path(font)}':text='{_esc_text(mark.text)}'"
        f":fontcolor={mark.color.replace('#', '0x')}:fontsize={mark.fontsize}"
        f":box=1:boxcolor={mark.box_color.replace('#', '0x')}@0.5:boxborderw=8"
        f":x={x}:y={y}"
    )


def _run(cmd: list[str], log: ProgressCb) -> None:
    log("ffmpeg 실행 중... (영상 길이에 따라 시간이 걸립니다)")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssembleError("영상 합성 실패:\n" + (proc.stderr.strip()[-1500:] or "?"))


def _remove_music(src_wav: str, log: ProgressCb) -> str:
    """demucs 로 음악 제거 후 보컬(음성)만 남긴 wav 반환. 실패 시 원본."""
    if not shutil.which("demucs"):
        log("  · demucs 미설치 → 원본 BGM 제거 건너뜀 (pip install demucs)")
        return src_wav
    try:
        outdir = os.path.join(os.path.dirname(src_wav) or ".", "demucs_out")
        subprocess.run(
            ["demucs", "--two-stems", "vocals", "-o", outdir, src_wav],
            capture_output=True, text=True, check=True,
        )
        for root, _d, files in os.walk(outdir):
            if "vocals.wav" in files:
                return os.path.join(root, "vocals.wav")
    except Exception as exc:  # noqa: BLE001
        log(f"  · BGM 제거 실패, 원본 사용: {exc}")
    return src_wav


def _dur(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _extract_original_audio(video_path: str, dst: str) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", video_path, "-vn", "-ac", "2", dst],
        capture_output=True, text=True,
    )
    return dst


def _build_video_filter(srt_path: Optional[str], opt: AssembleOptions,
                        log: ProgressCb) -> str:
    vfilters: list[str] = []
    if srt_path and os.path.exists(srt_path):
        style = srt_utils.force_style(
            font=opt.subtitle.font, fontsize=opt.subtitle.fontsize,
            primary=opt.subtitle.primary, outline=opt.subtitle.outline,
            back=opt.subtitle.back, box=opt.subtitle.box,
        )
        vfilters.append(f"subtitles='{_esc_sub_path(srt_path)}':force_style='{style}'")
    dt = _drawtext(opt.source)
    if dt:
        vfilters.append(dt)
    elif opt.source.text.strip():
        log("  · 출처 표시용 폰트를 못 찾아 워터마크를 건너뜁니다.")
    return ",".join(vfilters)


def build_video(
    video_path: str,
    wav_path: str,
    srt_path: Optional[str],
    output: str,
    options: Optional[AssembleOptions] = None,
    log: ProgressCb = lambda _m: None,
) -> str:
    """최종 영상을 합성해 output 경로로 저장."""
    if not shutil.which("ffmpeg"):
        raise AssembleError("ffmpeg 가 필요합니다.")
    for label, p in [("영상", video_path), ("음성(wav)", wav_path)]:
        if not p or not os.path.exists(p):
            raise AssembleError(f"{label} 파일을 찾을 수 없습니다: {p}")
    opt = options or AssembleOptions()

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", video_path, "-i", wav_path]

    # 입력 0 = 원본영상+원본오디오, 입력 1 = Vrew 나레이션 wav
    orig_audio = "0:a"

    # 원본 BGM 제거가 필요한 모드면 원본 오디오를 미리 정제해 입력 2 로 추가
    if opt.remove_original_bgm and opt.audio_mode in ("ambience", "dub"):
        log("  · 원본 BGM 제거 시도(demucs)...")
        raw = _extract_original_audio(video_path, os.path.splitext(output)[0] + "_orig.wav")
        cleaned = _remove_music(raw, log)
        cmd += ["-i", cleaned]
        orig_audio = "2:a"

    afilters: list[str] = []
    if opt.audio_mode == "replace":
        audio_map = "1:a"  # 나레이션만

    elif opt.audio_mode == "ambience":
        afilters.append(
            f"[{orig_audio}]volume={opt.ambience_volume}[amb];"
            f"[1:a]volume=1.0[nar];"
            f"[amb][nar]amix=inputs=2:duration=longest:normalize=0[aout]"
        )
        audio_map = "[aout]"

    elif opt.audio_mode == "dub":
        # 원음 구간에서는 원본 목소리 ON + 나레이션 DUCK, 그 외엔 원본 OFF + 나레이션 ON
        seg = _seg_expr(opt.original_segments)
        if seg == "0":
            log("  · '원음 유지 구간'이 비어 있어 나레이션만 나갑니다.")
        afilters.append(
            f"[{orig_audio}]volume=volume='if(gt({seg}\\,0)\\,1\\,0)':eval=frame[orig];"
            f"[1:a]volume=volume='if(gt({seg}\\,0)\\,{opt.narration_duck}\\,1)':eval=frame[nar];"
            f"[orig][nar]amix=inputs=2:duration=longest:normalize=0[aout]"
        )
        audio_map = "[aout]"
    else:
        raise AssembleError(f"알 수 없는 audio_mode: {opt.audio_mode}")

    # 비디오 필터
    vfilter = _build_video_filter(srt_path, opt, log)

    # 나레이션이 원본 영상보다 길면 마지막 프레임을 정지시켜 영상을 늘린다
    # (그래야 나레이션·자막이 잘리지 않는다).
    vdur, adur = _dur(video_path), _dur(wav_path)
    if adur > vdur + 0.05:
        pad = adur - vdur
        log(f"  · 나레이션이 {pad:.1f}초 더 길어 영상 끝 프레임을 늘립니다")
        tpad = f"tpad=stop_mode=clone:stop_duration={pad:.3f}"
        vfilter = f"{vfilter},{tpad}" if vfilter else tpad

    filter_parts = list(afilters)
    if vfilter:
        filter_parts.append(f"[0:v]{vfilter}[vout]")
        video_map = "[vout]"
    else:
        video_map = "0:v"

    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts)]
    cmd += ["-map", video_map, "-map", audio_map]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", output]

    _run(cmd, log)
    log(f"완성 → {output}")
    return output
