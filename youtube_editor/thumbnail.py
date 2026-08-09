"""썸네일 자동 생성 모듈 (영상 완성 후).

만드는 것:
  1) 대표 프레임 후보 여러 장
  2) 얼굴이 크고 선명한 프레임 후보 (영상에서 인물 찾기) — OpenCV YuNet
  3) 큰 한국어 제목 + 인물 얼굴을 얹은 유튜브용 썸네일 1280x720

얼굴 소스는 두 가지:
  - 사용자가 준 얼굴 사진(png/jpg)을 오른쪽에 합성 (제목은 왼쪽)
  - 영상에서 얼굴이 잘 잡힌 프레임을 자동 선택해 배경으로 사용
프레임 추출·자막은 ffmpeg, 얼굴 인식·합성은 OpenCV.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Optional

ProgressCb = Callable[[str], None]

_MODEL = os.path.join(os.path.dirname(__file__), "models", "yunet.onnx")


class ThumbnailError(Exception):
    pass


# ------------------------------------------------------------------ 폰트/유틸
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
    return title[:per_line] + "\n" + title[per_line:per_line * 2]


# ------------------------------------------------------------------ 얼굴 인식
def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise ThumbnailError(
            "얼굴 기능에는 OpenCV 가 필요합니다. `pip install opencv-python-headless`"
        ) from exc
    try:  # 잡다한 백엔드 경고 숨기기
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass
    return cv2


def _detector(cv2, w: int, h: int):
    if not os.path.exists(_MODEL):
        raise ThumbnailError(
            f"얼굴 인식 모델이 없습니다: {_MODEL} (yunet.onnx 를 넣어주세요)")
    det = cv2.FaceDetectorYN_create(_MODEL, "", (w, h), 0.6)
    det.setInputSize((w, h))
    return det


def detect_faces(bgr):
    """이미지(BGR)에서 얼굴 목록 [(x,y,w,h,score)] 반환. 없으면 []."""
    cv2 = _cv2()
    h, w = bgr.shape[:2]
    det = _detector(cv2, w, h)
    _, faces = det.detect(bgr)
    if faces is None:
        return []
    out = []
    for f in faces:
        x, y, fw, fh = (int(v) for v in f[:4])
        out.append((x, y, fw, fh, float(f[14])))
    return out


def _sharpness(cv2, bgr) -> float:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _scan_face_frames(video: str, samples: int = 40, log: ProgressCb = lambda _m: None):
    """영상을 훑어 얼굴이 있는 프레임을 (점수, 시각, 프레임) 로 모아 반환."""
    cv2 = _cv2()
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise ThumbnailError("영상을 열 수 없습니다.")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    results = []
    idxs = [int(total * i / (samples + 1)) for i in range(1, samples + 1)] if total else []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        faces = detect_faces(frame)
        if not faces:
            continue
        # 가장 큰 얼굴 기준: 얼굴 크기 × 선명도 × 인식점수
        x, y, fw, fh, sc = max(faces, key=lambda f: f[2] * f[3])
        score = (fw * fh) * sc * (1 + _sharpness(cv2, frame) / 1000.0)
        results.append((score, idx / fps, frame))
    cap.release()
    results.sort(key=lambda r: r[0], reverse=True)
    log(f"얼굴 있는 프레임 {len(results)}개 발견")
    return results


def _to_1280x720(cv2, frame):
    h, w = frame.shape[:2]
    scale = max(1280 / w, 720 / h)
    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    h, w = frame.shape[:2]
    x0 = (w - 1280) // 2
    y0 = (h - 720) // 2
    return frame[y0:y0 + 720, x0:x0 + 1280]


def extract_face_shots(
    video: str, out_dir: str, count: int = 5, log: ProgressCb = lambda _m: None,
) -> list[str]:
    """영상에서 얼굴이 잘 잡힌 프레임 후보를 뽑아 저장(1280x720)."""
    cv2 = _cv2()
    os.makedirs(out_dir, exist_ok=True)
    ranked = _scan_face_frames(video, log=log)
    paths = []
    for i, (_s, _t, frame) in enumerate(ranked[:count], 1):
        out = os.path.join(out_dir, f"face_shot_{i}.jpg")
        cv2.imwrite(out, _to_1280x720(cv2, frame))
        paths.append(out)
    if not paths:
        log("  · 얼굴이 있는 프레임을 찾지 못했습니다.")
    return paths


def best_face_time(video: str, log: ProgressCb = lambda _m: None) -> Optional[float]:
    """얼굴이 가장 잘 잡힌 프레임의 시각(초). 없으면 None."""
    ranked = _scan_face_frames(video, log=log)
    return ranked[0][1] if ranked else None


# ------------------------------------------------------------------ 후보/합성
def extract_candidates(
    video: str, out_dir: str, count: int = 5, log: ProgressCb = lambda _m: None,
) -> list[str]:
    """균등 간격 대표 프레임 후보(얼굴 무관)."""
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


def _overlay_face(base_bgr, face_path: str, cv2, log: ProgressCb) -> "any":
    """오른쪽에 인물 얼굴 사진을 합성. 투명 PNG면 알파 반영."""
    ov = cv2.imread(face_path, cv2.IMREAD_UNCHANGED)
    if ov is None:
        log(f"  · 얼굴 사진을 열 수 없습니다: {face_path}")
        return base_bgr
    H, W = base_bgr.shape[:2]
    oh, ow = ov.shape[:2]

    # 세로 꽉 차게 스케일
    target_h = int(H * 0.98)
    scale = target_h / oh
    target_w = int(ow * scale)
    cap_w = int(W * 0.58)  # 오른쪽 절반 남짓까지만
    ov = cv2.resize(ov, (target_w, target_h), interpolation=cv2.INTER_AREA)
    if target_w > cap_w:  # 너무 넓으면 가로 중앙 크롭
        x0 = (target_w - cap_w) // 2
        ov = ov[:, x0:x0 + cap_w]
        target_w = cap_w

    x = W - target_w - 20
    y = H - target_h
    roi = base_bgr[y:y + target_h, x:x + target_w]
    if ov.shape[2] == 4:  # 알파 블렌딩
        alpha = ov[:, :, 3:4].astype(float) / 255.0
        roi[:] = (ov[:, :, :3].astype(float) * alpha
                  + roi.astype(float) * (1 - alpha)).astype("uint8")
    else:
        roi[:] = ov[:, :, :3]
    return base_bgr


def make_thumbnail(
    video: str,
    output: str,
    title: str = "",
    at: Optional[float] = None,
    face_image: Optional[str] = None,
    pick_face: bool = False,
    accent: str = "#FFE500",
    log: ProgressCb = lambda _m: None,
) -> str:
    """대표 프레임 + (선택)인물 얼굴 + 제목으로 유튜브 썸네일 생성.

    face_image: 오른쪽에 합성할 인물 사진 경로.
    pick_face : True 면 영상에서 얼굴이 잘 잡힌 프레임을 배경으로 자동 선택.
    """
    if not shutil.which("ffmpeg"):
        raise ThumbnailError("ffmpeg 가 필요합니다.")

    # 배경 프레임 시각 결정
    if at is None and pick_face:
        try:
            t = best_face_time(video, log=log)
            if t is not None:
                at = t
                log(f"  · 얼굴 프레임 자동 선택: {t:.1f}초")
        except ThumbnailError as exc:
            log(f"  · 얼굴 자동 선택 건너뜀: {exc}")

    # 1) 베이스 프레임(1280x720)
    base = os.path.splitext(output)[0] + "_base.jpg"
    scale = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720"
    if at is not None:
        cmd = ["-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", "-vf", scale]
    else:
        cmd = ["-i", video, "-frames:v", "1", "-vf", f"thumbnail=100,{scale}"]
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *cmd, base],
                   capture_output=True, text=True)
    if not os.path.exists(base):
        raise ThumbnailError("베이스 프레임을 뽑지 못했습니다.")

    face_layout = bool(face_image)
    # 2) 인물 얼굴 합성 (선택)
    if face_layout:
        cv2 = _cv2()
        img = cv2.imread(base)
        img = _overlay_face(img, face_image, cv2, log)
        cv2.imwrite(base, img)

    # 3) 제목/음영/악센트
    if face_layout:
        # 왼쪽에 제목 → 왼쪽을 어둡게, 제목 왼쪽 정렬
        filters = ["drawbox=x=0:y=0:w=700:h=720:color=black@0.45:t=fill"]
        title_font, title_x, per_line = 78, "50", 8
    else:
        filters = ["drawbox=x=0:y=460:w=1280:h=260:color=black@0.45:t=fill"]
        title_font, title_x, per_line = 88, "(w-text_w)/2", 11

    if title.strip():
        font = _font()
        if font:
            filters.insert(0,
                           f"drawbox=x=0:y=0:w=16:h=720:color={accent.replace('#','0x')}:t=fill")
            y_expr = "(h-text_h)/2" if face_layout else "h-text_h-60"
            filters.append(
                f"drawtext=fontfile='{_esc(font)}':text='{_esc(_wrap(title, per_line))}'"
                f":fontcolor=white:fontsize={title_font}:line_spacing=12"
                f":borderw=6:bordercolor=black:box=0:x={title_x}:y={y_expr}")
        else:
            log("  · 한글 폰트를 못 찾아 제목 없이 생성합니다.")

    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", base, "-vf", ",".join(filters), "-frames:v", "1", output],
        capture_output=True, text=True,
    )
    try:
        os.remove(base)
    except OSError:
        pass
    if not os.path.exists(output):
        raise ThumbnailError("썸네일 생성에 실패했습니다.")
    log(f"썸네일 완성 → {output}")
    return output
