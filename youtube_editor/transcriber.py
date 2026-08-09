"""원어 자막 생성 모듈 (음성인식).

faster-whisper 로 영상의 원어 음성을 인식해 단어 단위 타임스탬프가 붙은
문장 자막(SRT)과 대본용 텍스트를 만든다. (자동편집기 2단계에 해당)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from .srt_utils import Cue, build_srt


class TranscribeError(Exception):
    pass


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class TranscriptResult:
    language: str
    language_prob: float
    segments: list[Segment]

    # ------------------------------------------------------------------ views
    def to_srt(self) -> str:
        """문장 단위 SRT 문자열."""
        cues = [
            Cue(i + 1, s.start, s.end, s.text.strip())
            for i, s in enumerate(self.segments)
            if s.text.strip()
        ]
        return build_srt(cues)

    def to_text(self) -> str:
        """대본 생성기(Claude)에 붙여넣을 순수 텍스트."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    @property
    def sentence_count(self) -> int:
        return sum(1 for s in self.segments if s.text.strip())


ProgressCb = Callable[[str], None]


def extract_audio_wav(src: str, dst: Optional[str] = None) -> str:
    """음성인식용으로 16kHz 모노 WAV 추출."""
    if not shutil.which("ffmpeg"):
        raise TranscribeError("ffmpeg 가 필요합니다.")
    dst = dst or os.path.join(tempfile.gettempdir(), "yte_asr_input.wav")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", dst,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscribeError("소리 추출 실패: " + (proc.stderr.strip() or "?"))
    return dst


class Transcriber:
    """faster-whisper 래퍼."""

    def __init__(self, model_size: str = "small", device: str = "auto"):
        self.model_size = model_size
        self.device = device
        self._model = None

    def _load(self, log: ProgressCb) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscribeError(
                "faster-whisper 가 필요합니다. `pip install faster-whisper` 후 다시 시도하세요."
            ) from exc
        log("[1/3] 인식 모델 준비 중 — 처음 한 번은 다운로드로 몇 분 걸려요...")
        device = self.device
        compute = "int8"
        if device == "auto":
            try:
                import torch  # noqa: F401
                if torch.cuda.is_available():
                    device, compute = "cuda", "float16"
                else:
                    device = "cpu"
            except Exception:
                device = "cpu"
        self._model = WhisperModel(self.model_size, device=device, compute_type=compute)

    def transcribe(self, src: str, log: ProgressCb = lambda _m: None) -> TranscriptResult:
        """영상/오디오 파일을 인식해 TranscriptResult 반환."""
        log("[1/3] 영상에서 소리를 뽑는 중...")
        wav = extract_audio_wav(src)
        self._load(log)

        log("[3/3] 음성 인식 중 — 0%")
        segments_iter, info = self._model.transcribe(
            wav, word_timestamps=True, vad_filter=True,
        )
        log(f"감지된 언어: {info.language} (확신 {int(info.language_probability * 100)}%)")

        total = float(info.duration or 0) or 1.0
        segments: list[Segment] = []
        last_pct = 0
        for seg in segments_iter:
            words = [
                Word(w.start, w.end, w.word)
                for w in (seg.words or [])
                if w.start is not None
            ]
            segments.append(Segment(seg.start, seg.end, seg.text, words))
            pct = min(99, int(seg.end / total * 100))
            if pct >= last_pct + 10:
                last_pct = pct
                log(f"[3/3] 음성 인식 중 — {pct}% ({len(segments)}문장)")

        log(f"원어 자막 완성 — {len(segments)}문장 (단어 단위 정렬)")
        return TranscriptResult(
            language=info.language,
            language_prob=float(info.language_probability),
            segments=segments,
        )
