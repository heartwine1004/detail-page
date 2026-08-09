"""유튜브 다운로드 & 편집 웹 앱 (Flask).

브라우저에서 유튜브 링크를 붙여넣고, 정보 조회 → 다운로드 → 편집(자르기/변환/
오디오 추출/속도)을 버튼으로 실행한다.

실행:
    python webapp/app.py
    -> http://127.0.0.1:5000
"""

from __future__ import annotations

import os
import sys

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

# 프로젝트 루트를 import 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from youtube_editor import Downloader, DownloadError, Editor, EditorError  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

app = Flask(__name__)
downloader = Downloader(DOWNLOAD_DIR)


def _editor() -> Editor:
    # ffmpeg 미설치 시 여기서 EditorError 발생 → 라우트에서 처리
    return Editor(DOWNLOAD_DIR)


def _rel(path: str) -> str:
    """다운로드 폴더 기준 상대 경로 (다운로드 링크용)."""
    return os.path.relpath(path, DOWNLOAD_DIR)


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/info")
def api_info():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify(error="링크를 입력하세요."), 400
    try:
        info = downloader.get_info(url)
    except DownloadError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(info.as_dict())


@app.post("/api/download")
def api_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    quality = data.get("quality")
    if not url:
        return jsonify(error="링크를 입력하세요."), 400
    try:
        path = downloader.download(url, max_height=int(quality) if quality else None)
    except (DownloadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(file=_rel(path), name=os.path.basename(path))


@app.post("/api/edit")
def api_edit():
    """단일 편집 작업 실행.

    body: { file, action, ... }
      action=trim   : start, end, fast
      action=convert: height, format
      action=audio  : format
      action=speed  : factor
    """
    data = request.json or {}
    rel = data.get("file", "")
    action = data.get("action", "")
    src = os.path.join(DOWNLOAD_DIR, rel)

    # 경로 탈출 방지
    if not os.path.abspath(src).startswith(os.path.abspath(DOWNLOAD_DIR)):
        return jsonify(error="잘못된 파일 경로입니다."), 400
    if not os.path.exists(src):
        return jsonify(error="파일을 찾을 수 없습니다. 먼저 다운로드하세요."), 400

    try:
        ed = _editor()
        if action == "trim":
            out = ed.trim(src, data["start"], data["end"], fast=bool(data.get("fast")))
        elif action == "convert":
            out = ed.convert(
                src,
                height=int(data["height"]) if data.get("height") else None,
                fmt=data.get("format", "mp4"),
            )
        elif action == "audio":
            out = ed.extract_audio(src, fmt=data.get("format", "mp3"))
        elif action == "speed":
            out = ed.change_speed(src, float(data["factor"]))
        else:
            return jsonify(error=f"알 수 없는 작업: {action}"), 400
    except (EditorError, KeyError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(file=_rel(out), name=os.path.basename(out))


@app.route("/downloads/<path:filename>")
def download_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"  ▶ http://127.0.0.1:{port} 에서 실행 중")
    app.run(host="127.0.0.1", port=port, debug=False)
