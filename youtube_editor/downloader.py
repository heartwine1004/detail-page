"""유튜브 다운로드 모듈 (yt-dlp 래퍼).

링크에서 영상 정보를 조회하고, 편집 가능한 mp4 파일로 내려받는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import yt_dlp
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "yt-dlp 가 필요합니다. `pip install -r requirements.txt` 를 실행하세요."
    ) from exc


class DownloadError(Exception):
    """다운로드 중 발생한 오류."""


@dataclass
class VideoInfo:
    """영상 메타데이터 (편집 UI 표시용)."""

    id: str
    title: str
    duration: int  # 초
    uploader: str
    thumbnail: str
    webpage_url: str
    resolutions: list[int] = field(default_factory=list)  # 선택 가능한 화질(높이)

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration or 0), 60)
        h, m = divmod(m, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "duration": self.duration,
            "duration_str": self.duration_str,
            "uploader": self.uploader,
            "thumbnail": self.thumbnail,
            "webpage_url": self.webpage_url,
            "resolutions": self.resolutions,
        }


ProgressHook = Callable[[dict[str, Any]], None]


class Downloader:
    """yt-dlp 기반 유튜브 다운로더."""

    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------ info
    def get_info(self, url: str) -> VideoInfo:
        """영상을 내려받지 않고 메타데이터만 조회한다."""
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(f"영상 정보를 가져오지 못했습니다: {exc}") from exc

        if data is None:
            raise DownloadError("영상 정보를 가져오지 못했습니다.")

        # 재생목록 링크면 첫 번째 항목 사용
        if data.get("_type") == "playlist" and data.get("entries"):
            data = data["entries"][0]

        heights = sorted(
            {
                f["height"]
                for f in data.get("formats", [])
                if f.get("height") and f.get("vcodec") not in (None, "none")
            }
        )

        return VideoInfo(
            id=data.get("id", ""),
            title=data.get("title", "untitled"),
            duration=int(data.get("duration") or 0),
            uploader=data.get("uploader", ""),
            thumbnail=data.get("thumbnail", ""),
            webpage_url=data.get("webpage_url", url),
            resolutions=heights,
        )

    # -------------------------------------------------------------- download
    def download(
        self,
        url: str,
        max_height: Optional[int] = None,
        progress_hook: Optional[ProgressHook] = None,
    ) -> str:
        """영상을 mp4 로 내려받고 저장 경로를 반환한다.

        max_height: 지정하면 해당 화질 이하로 다운로드 (예: 720). None 이면 최고 화질.
        """
        # 영상+오디오를 합쳐 편집하기 좋은 mp4 로 받는다.
        if max_height:
            fmt = (
                f"bestvideo[height<={max_height}]+bestaudio/"
                f"best[height<={max_height}]/best"
            )
        else:
            fmt = "bestvideo+bestaudio/best"

        outtmpl = os.path.join(self.output_dir, "%(title).80s-%(id)s.%(ext)s")
        opts: dict[str, Any] = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            # 편집 도구가 확실히 다룰 수 있도록 mp4(H.264/AAC)로 맞춘다.
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
            ],
        }
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(url, download=True)
                if data.get("_type") == "playlist" and data.get("entries"):
                    data = data["entries"][0]
                path = ydl.prepare_filename(data)
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(f"다운로드 실패: {exc}") from exc

        # 후처리로 확장자가 mp4 로 바뀌었을 수 있으니 보정
        base, _ = os.path.splitext(path)
        mp4_path = base + ".mp4"
        if os.path.exists(mp4_path):
            return mp4_path
        if os.path.exists(path):
            return path
        raise DownloadError("다운로드는 끝났지만 결과 파일을 찾지 못했습니다.")
