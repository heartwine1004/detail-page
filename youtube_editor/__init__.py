"""YouTube 다운로드 & 편집 핵심 패키지.

- downloader: 유튜브 링크에서 영상 정보 조회 / 다운로드 (yt-dlp)
- editor:     내려받은 영상 편집 - 자르기 / 변환 / 오디오 추출 / 속도 (ffmpeg)
"""

from .downloader import Downloader, VideoInfo, DownloadError
from .editor import Editor, EditorError

__all__ = [
    "Downloader",
    "VideoInfo",
    "DownloadError",
    "Editor",
    "EditorError",
]

__version__ = "0.1.0"
