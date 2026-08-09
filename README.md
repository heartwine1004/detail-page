# 🎬 유튜브 다운로드 & 편집기

유튜브 영상 링크를 주면 **편집할 수 있게 다운로드**하고, 곧바로
**자르기 · 화질/포맷 변환 · 오디오 추출 · 속도 조절**까지 해 주는 프로그램입니다.

- **웹 UI**: 브라우저에서 링크 붙여넣고 버튼으로 편집 (비개발자 친화적)
- **CLI**: 터미널 명령 한 줄로 다운로드+편집 (자동화에 유리)
- 내부는 [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)(다운로드) + [`ffmpeg`](https://ffmpeg.org)(편집)

---

## ⚖️ 사용 전 안내

- 본인이 저작권을 가졌거나, 다운로드·편집이 허용된 영상만 이용하세요.
- 유튜브 서비스 약관과 저작권법을 준수하는 것은 사용자 책임입니다.

---

## 1. 설치

```bash
# 1) 파이썬 패키지
pip install -r requirements.txt

# 2) ffmpeg (편집에 필요)
#   Ubuntu/Debian : sudo apt-get install ffmpeg
#   macOS (brew)  : brew install ffmpeg
#   Windows       : https://ffmpeg.org/download.html 에서 받아 PATH 등록
```

## 2. 웹 UI로 사용하기 (추천)

```bash
python webapp/app.py
# 브라우저에서 http://127.0.0.1:5000 접속
```

사용 흐름: **링크 붙여넣기 → 정보 조회 → 다운로드 → 편집 버튼 클릭 → 결과 저장**

## 3. 명령줄(CLI)로 사용하기

```bash
# 영상 정보 보기
python cli.py info "https://youtu.be/XXXX"

# 720p 로 다운로드
python cli.py download "https://youtu.be/XXXX" --quality 720

# 다운로드 + 0:10~1:30 구간 잘라내기 (한 번에)
python cli.py edit "https://youtu.be/XXXX" --trim 0:10 1:30

# 다운로드 + 720p 변환 + mp3 추출 + 1.5배속 을 한 번에
python cli.py edit "https://youtu.be/XXXX" --quality 1080 --convert 720 --audio mp3 --speed 1.5

# 이미 받은 로컬 파일 편집
python cli.py trim    downloads/video.mp4 0:05 0:20
python cli.py convert downloads/video.mp4 --quality 480 --format mp4
python cli.py audio   downloads/video.mp4 --format mp3
```

결과물은 모두 `downloads/` 폴더에 저장됩니다.

---

## 편집 기능

| 기능 | 설명 |
|------|------|
| **구간 자르기(trim)** | 시작~끝 시간을 지정해 원하는 부분만 추출. `--fast` 는 재인코딩 없이 빠르게(키프레임 단위) |
| **화질/포맷 변환** | 1080p→720p 등 해상도 변경, mp4/webm/mkv 컨테이너 변환 |
| **오디오 추출** | 영상에서 소리만 뽑아 mp3/m4a/wav 로 저장 |
| **속도 조절** | 0.5배~2배 등 재생 속도 변경(영상+오디오 동기 유지) |

---

## 프로젝트 구조

```
.
├── youtube_editor/       # 핵심 로직 (CLI·웹 공용)
│   ├── downloader.py     #   yt-dlp 래퍼: 정보 조회 / 다운로드
│   └── editor.py         #   ffmpeg 래퍼: 자르기 / 변환 / 오디오 / 속도
├── cli.py                # 명령줄 인터페이스
├── webapp/
│   ├── app.py            # Flask 백엔드 (REST API)
│   └── templates/index.html  # 웹 UI
├── downloads/            # 결과물 저장 폴더
└── requirements.txt
```

## 참고 / 한계

- 시간이 오래 걸리는 다운로드·인코딩은 완료될 때까지 기다려야 합니다(진행 표시 있음).
- 유튜브 쪽 변경으로 다운로드가 막히면 `pip install -U yt-dlp` 로 최신화하세요.
- 웹 UI는 로컬(개인 PC) 사용을 전제로 합니다. 외부 공개 시 인증/보안을 추가하세요.
