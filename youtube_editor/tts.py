"""음성 생성 모듈 (Vrew 대체) — 대본 → 음성(wav) + 자막(srt).

문장 단위로 음성을 합성해 각 문장의 길이를 재고, 그 타이밍으로 SRT 를
자동 생성한다. 덕분에 음성과 자막 싱크가 정확하다.

엔진(engine):
  - EdgeEngine  : edge-tts (무료 온라인, 한국어 남/여 음성)
  - CloneEngine : Coqui XTTS-v2 로 '내 목소리 샘플'을 복제해 그 목소리로 읽기
  - ElevenLabsEngine : (선택) ElevenLabs API 음성 복제
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable, Optional

from . import script_tools
from .srt_utils import Cue, build_srt

ProgressCb = Callable[[str], None]

# 자주 쓰는 한국어 edge-tts 음성
KO_VOICES = {
    "ko-KR-SunHiNeural": "선히 (여, 기본)",
    "ko-KR-InJoonNeural": "인준 (남)",
    "ko-KR-JiMinNeural": "지민 (여)",
    "ko-KR-SeoHyeonNeural": "서현 (여)",
    "ko-KR-YuJinNeural": "유진 (여)",
    "ko-KR-BongJinNeural": "봉진 (남)",
    "ko-KR-GookMinNeural": "국민 (남)",
    "ko-KR-HyunsuMultilingualNeural": "현수 (남, 다국어)",
}


class TTSError(Exception):
    pass


def split_sentences(script_text: str) -> list[str]:
    """대본 텍스트를 문장 리스트로 (마크다운 정리 + 문장 분리)."""
    return [s for s in script_tools.format_for_vrew(script_text).split("\n") if s.strip()]


def _ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _to_wav(src: str, dst: str, sr: int) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", src, "-ac", "1", "-ar", str(sr), dst],
        capture_output=True, text=True, check=True,
    )


def _make_silence(seconds: float, sr: int, dst: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=mono",
         "-t", f"{seconds:.3f}", dst],
        capture_output=True, text=True, check=True,
    )


# ------------------------------------------------------------------ 엔진들
class TTSEngine:
    sample_rate = 24000

    def synth(self, text: str, out_wav: str) -> None:
        raise NotImplementedError


class EdgeEngine(TTSEngine):
    """edge-tts (무료). 인터넷 필요."""

    def __init__(self, voice: str = "ko-KR-SunHiNeural", rate: str = "+0%"):
        self.voice = voice
        self.rate = rate

    def synth(self, text: str, out_wav: str) -> None:
        try:
            import asyncio
            import edge_tts
        except ImportError as exc:
            raise TTSError("edge-tts 가 필요합니다. `pip install edge-tts`") from exc
        mp3 = out_wav + ".mp3"
        try:
            asyncio.run(
                edge_tts.Communicate(text, self.voice, rate=self.rate).save(mp3)
            )
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"edge-tts 음성 생성 실패: {exc}") from exc
        _to_wav(mp3, out_wav, self.sample_rate)
        try:
            os.remove(mp3)
        except OSError:
            pass


class CloneEngine(TTSEngine):
    """Coqui XTTS-v2 음성 복제. '내 목소리 샘플(wav)' 로 읽어준다."""

    sample_rate = 24000

    def __init__(self, speaker_wav: str, language: str = "ko",
                 model: str = "tts_models/multilingual/multi-dataset/xtts_v2"):
        if not speaker_wav or not os.path.exists(speaker_wav):
            raise TTSError(f"음성 샘플 파일이 없습니다: {speaker_wav}")
        self.speaker_wav = speaker_wav
        self.language = language
        self.model = model
        self._tts = None

    def _load(self):
        if self._tts is not None:
            return
        try:
            import torch  # noqa: F401
            from TTS.api import TTS
        except ImportError as exc:
            raise TTSError(
                "음성 복제에는 Coqui TTS 가 필요합니다. `pip install TTS`"
            ) from exc
        gpu = False
        try:
            import torch
            gpu = torch.cuda.is_available()
        except Exception:  # noqa: BLE001
            pass
        self._tts = TTS(self.model, gpu=gpu)

    def synth(self, text: str, out_wav: str) -> None:
        self._load()
        raw = out_wav + ".raw.wav"
        self._tts.tts_to_file(
            text=text, speaker_wav=self.speaker_wav, language=self.language,
            file_path=raw,
        )
        _to_wav(raw, out_wav, self.sample_rate)
        try:
            os.remove(raw)
        except OSError:
            pass


class ElevenLabsEngine(TTSEngine):
    """(선택) ElevenLabs API 음성 복제. api_key + voice_id 필요."""

    def __init__(self, api_key: str, voice_id: str):
        self.api_key = api_key
        self.voice_id = voice_id

    def synth(self, text: str, out_wav: str) -> None:
        try:
            import requests
        except ImportError as exc:
            raise TTSError("requests 가 필요합니다.") from exc
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        r = requests.post(
            url,
            headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=120,
        )
        if r.status_code != 200:
            raise TTSError(f"ElevenLabs 실패: {r.status_code} {r.text[:200]}")
        mp3 = out_wav + ".mp3"
        with open(mp3, "wb") as f:
            f.write(r.content)
        _to_wav(mp3, out_wav, self.sample_rate)
        os.remove(mp3)


# ------------------------------------------------------------------ 오케스트레이터
def synthesize_script(
    script_text: str,
    engine: TTSEngine,
    out_wav: str,
    out_srt: str,
    gap: float = 0.35,
    log: ProgressCb = lambda _m: None,
) -> tuple[str, str]:
    """대본 → 음성(wav) + 자막(srt). 문장별 길이로 자막 싱크를 맞춘다."""
    sentences = split_sentences(script_text)
    if not sentences:
        raise TTSError("대본에서 문장을 찾지 못했습니다.")
    sr = engine.sample_rate
    tmp = tempfile.mkdtemp(prefix="yte_tts_")
    silence = os.path.join(tmp, "gap.wav")
    _make_silence(gap, sr, silence)

    cues: list[Cue] = []
    parts: list[str] = []
    cursor = 0.0
    total = len(sentences)
    for i, sentence in enumerate(sentences):
        wav_i = os.path.join(tmp, f"s{i:04d}.wav")
        engine.synth(sentence, wav_i)
        dur = _ffprobe_duration(wav_i)
        cues.append(Cue(i + 1, cursor, cursor + dur, sentence))
        cursor += dur
        parts.append(wav_i)
        if i < total - 1:
            parts.append(silence)
            cursor += gap
        if (i + 1) % 5 == 0 or i + 1 == total:
            log(f"  음성 생성 {i + 1}/{total} 문장...")

    # 이어붙이기 (concat demuxer)
    listfile = os.path.join(tmp, "list.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", listfile,
         "-ac", "1", "-ar", str(sr), out_wav],
        capture_output=True, text=True, check=True,
    )

    with open(out_srt, "w", encoding="utf-8") as f:
        f.write(build_srt(cues))

    log(f"음성·자막 완성 — {total}문장, 길이 {cursor:.1f}초")
    return out_wav, out_srt
