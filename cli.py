#!/usr/bin/env python3
"""유튜브 다운로드 & 편집 CLI.

예시:
  # 영상 정보 보기
  python cli.py info "https://youtu.be/XXXX"

  # 720p 로 다운로드
  python cli.py download "https://youtu.be/XXXX" --quality 720

  # 다운로드 + 0:10~1:30 구간 잘라내기 (한 번에)
  python cli.py edit "https://youtu.be/XXXX" --trim 0:10 1:30

  # 이미 받은 파일에서 오디오만 추출
  python cli.py audio downloads/video.mp4 --format mp3
"""

from __future__ import annotations

import argparse
import sys

from youtube_editor import Downloader, DownloadError, Editor, EditorError

OUT_DIR = "downloads"


def _progress(d: dict) -> None:
    if d.get("status") == "downloading":
        pct = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        print(f"\r  다운로드 중... {pct} {speed}   ", end="", flush=True)
    elif d.get("status") == "finished":
        print("\r  다운로드 완료. 후처리 중...            ")


def cmd_info(args) -> int:
    info = Downloader(OUT_DIR).get_info(args.url)
    print(f"제목    : {info.title}")
    print(f"업로더  : {info.uploader}")
    print(f"길이    : {info.duration_str}")
    print(f"화질    : {', '.join(f'{h}p' for h in info.resolutions) or '알 수 없음'}")
    print(f"링크    : {info.webpage_url}")
    return 0


def cmd_download(args) -> str:
    print(f"[*] 다운로드: {args.url}")
    path = Downloader(OUT_DIR).download(
        args.url, max_height=args.quality, progress_hook=_progress
    )
    print(f"[+] 저장됨: {path}")
    return path


def cmd_edit(args) -> int:
    path = cmd_download(args)
    editor = Editor(OUT_DIR)
    if args.trim:
        start, end = args.trim
        print(f"[*] 자르기: {start} ~ {end}")
        path = editor.trim(path, start, end, fast=args.fast)
        print(f"[+] 저장됨: {path}")
    if args.convert:
        print(f"[*] 변환: {args.convert}p")
        path = editor.convert(path, height=args.convert)
        print(f"[+] 저장됨: {path}")
    if args.audio:
        print(f"[*] 오디오 추출: {args.audio}")
        out = editor.extract_audio(path, fmt=args.audio)
        print(f"[+] 저장됨: {out}")
    if args.speed:
        print(f"[*] 속도 변경: {args.speed}x")
        path = editor.change_speed(path, args.speed)
        print(f"[+] 저장됨: {path}")
    return 0


def cmd_trim(args) -> int:
    out = Editor(OUT_DIR).trim(args.file, args.start, args.end, fast=args.fast)
    print(f"[+] 저장됨: {out}")
    return 0


def cmd_convert(args) -> int:
    out = Editor(OUT_DIR).convert(args.file, height=args.quality, fmt=args.format)
    print(f"[+] 저장됨: {out}")
    return 0


def cmd_audio(args) -> int:
    out = Editor(OUT_DIR).extract_audio(args.file, fmt=args.format)
    print(f"[+] 저장됨: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="유튜브 영상 다운로드 & 편집 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="영상 정보 조회")
    s.add_argument("url")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("download", help="영상 다운로드")
    s.add_argument("url")
    s.add_argument("--quality", type=int, help="최대 화질(세로 픽셀), 예: 720")
    s.set_defaults(func=lambda a: (cmd_download(a), 0)[1])

    s = sub.add_parser("edit", help="다운로드 + 편집을 한 번에")
    s.add_argument("url")
    s.add_argument("--quality", type=int, help="다운로드 화질(세로 픽셀)")
    s.add_argument("--trim", nargs=2, metavar=("START", "END"),
                   help="자를 구간, 예: --trim 0:10 1:30")
    s.add_argument("--convert", type=int, metavar="HEIGHT",
                   help="편집 후 변환할 화질(세로 픽셀)")
    s.add_argument("--audio", metavar="FMT", help="오디오 추출 (mp3/wav/m4a)")
    s.add_argument("--speed", type=float, help="속도 배수, 예: 1.5")
    s.add_argument("--fast", action="store_true",
                   help="자르기를 재인코딩 없이 빠르게(키프레임 단위)")
    s.set_defaults(func=cmd_edit)

    s = sub.add_parser("trim", help="로컬 파일 구간 자르기")
    s.add_argument("file")
    s.add_argument("start")
    s.add_argument("end")
    s.add_argument("--fast", action="store_true")
    s.set_defaults(func=cmd_trim)

    s = sub.add_parser("convert", help="로컬 파일 화질/포맷 변환")
    s.add_argument("file")
    s.add_argument("--quality", type=int, help="세로 픽셀, 예: 720")
    s.add_argument("--format", default="mp4", help="컨테이너 포맷 (기본 mp4)")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("audio", help="로컬 파일에서 오디오 추출")
    s.add_argument("file")
    s.add_argument("--format", default="mp3", help="mp3/wav/m4a (기본 mp3)")
    s.set_defaults(func=cmd_audio)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (DownloadError, EditorError) as exc:
        print(f"\n[오류] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단됨.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
