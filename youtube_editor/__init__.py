"""YouTube 다운로드 & 자동편집 핵심 패키지.

- downloader:   유튜브 링크 → 영상 정보 조회 / 다운로드 (yt-dlp)
- transcriber:  원어 음성인식 → 자막(SRT)·대본 텍스트 (faster-whisper)
- script_tools: 대본 스크립트(3·4단계) 유틸 - Claude 프롬프트 / Vrew 정리
- assembler:    최종 영상 합성(6단계) - 나레이션·자막·출처·부분더빙
- editor:       단순 편집 - 자르기/변환/오디오 추출/속도 (ffmpeg)
"""

from .downloader import Downloader, VideoInfo, DownloadError
from .editor import Editor, EditorError
from .transcriber import Transcriber, TranscriptResult, TranscribeError
from .assembler import (
    AssembleOptions,
    AssembleError,
    SubStyle,
    SourceMark,
    build_video,
)
from .tts import (
    synthesize_script,
    EdgeEngine,
    CloneEngine,
    ElevenLabsEngine,
    TTSError,
    KO_VOICES,
)
from . import script_tools, srt_utils, tts

__all__ = [
    "Downloader", "VideoInfo", "DownloadError",
    "Editor", "EditorError",
    "Transcriber", "TranscriptResult", "TranscribeError",
    "AssembleOptions", "AssembleError", "SubStyle", "SourceMark", "build_video",
    "synthesize_script", "EdgeEngine", "CloneEngine", "ElevenLabsEngine",
    "TTSError", "KO_VOICES",
    "script_tools", "srt_utils", "tts",
]

__version__ = "0.2.0"
