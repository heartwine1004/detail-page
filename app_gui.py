#!/usr/bin/env python3
"""자동편집기 (벤치마크) — 데스크톱 GUI.

외국 유튜브 영상을 한국어 더빙·자막 콘텐츠로 자동 재편집하는 도구.
스크린샷의 자동편집기 워크플로우(6단계)를 그대로 구현한다.

  1. 유튜브 링크 붙여넣기 (또는 영상 파일)
  2. 원어 자막 만들기 (음성인식)
  3. 대본용 스크립트 뽑기 → 클립보드 → Claude 로 한국어 대본 생성
  4. 받은 대본 붙여넣기 → Vrew 용 음성 대본 정리
  5. Vrew 파일 선택 (음성 wav + 자막 srt)
  6. 영상 만들기 (나레이션 + 자막 + 출처 + 부분더빙)

실행:  python app_gui.py   (Python 3.10+, tkinter 필요)
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from youtube_editor import (
    AssembleOptions,
    CloneEngine,
    DEFAULT_MODEL,
    Downloader,
    EdgeEngine,
    KO_VOICES,
    SourceMark,
    SubStyle,
    Transcriber,
    build_video,
    extract_candidates,
    extract_face_shots,
    generate_korean_script,
    make_thumbnail,
    script_tools,
    synthesize_script,
)
from youtube_editor.editor import parse_time

# ------------------------------------------------------------------ 색/스타일
BLUE = "#2b6cff"
BLUE_DARK = "#1e50c8"
BG = "#eef1f6"
CARD = "#ffffff"
LINE = "#d6dbe4"
TEXT = "#1b2430"
MUTED = "#7a8394"
FONT = ("Malgun Gothic", 10)
FONT_B = ("Malgun Gothic", 10, "bold")
FONT_H = ("Malgun Gothic", 15, "bold")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class AutoEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("자동편집기 v1.43k (벤치마크)")
        root.geometry("640x900")
        root.configure(bg=BG)

        # ---- 상태 ----
        self.video_path: str | None = None
        self.channel_name: str = ""
        self.video_title: str = ""
        self.orig_srt: str | None = None
        self.transcript = None
        self.wav_path: str | None = None
        self.srt_path: str | None = None
        self.last_output: str | None = None

        self.downloader = Downloader(DOWNLOAD_DIR)
        self.log_q: queue.Queue[str] = queue.Queue()

        self._build_ui()
        self.root.after(100, self._drain_log)

    # ============================================================== UI 빌드
    def _build_ui(self):
        # 스크롤 캔버스
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg=BG)
        self.body.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        win = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"),
        )

        # ---- 헤더 ----
        head = tk.Frame(self.body, bg=BLUE)
        head.pack(fill="x")
        tk.Label(head, text="자동편집기", bg=BLUE, fg="white",
                 font=FONT_H).pack(side="left", padx=16, pady=12)
        tk.Label(head, text="v1.43k (벤치마크)", bg=BLUE, fg="#d6e2ff",
                 font=FONT).pack(side="right", padx=16)

        pad = tk.Frame(self.body, bg=BG)
        pad.pack(fill="both", expand=True, padx=14, pady=12)
        self.cards = pad

        self._step1(pad)
        self._step2(pad)
        self._step3(pad)
        self._step4(pad)
        self._step5(pad)
        self._step6(pad)
        self._settings(pad)
        self._logbox(pad)

    def _card(self, parent, num: str, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="x", pady=6)
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(top, text=f" {num} ", bg=BLUE, fg="white",
                 font=FONT_B).pack(side="left")
        tk.Label(top, text="  " + title, bg=CARD, fg=TEXT,
                 font=FONT_B).pack(side="left")
        return card

    def _btn(self, parent, text, cmd, primary=True):
        b = tk.Button(parent, text=text, command=cmd, font=FONT_B,
                      bg=BLUE if primary else "#eaeef5",
                      fg="white" if primary else TEXT,
                      activebackground=BLUE_DARK if primary else "#dde3ec",
                      activeforeground="white" if primary else TEXT,
                      relief="flat", bd=0, padx=14, pady=6, cursor="hand2")
        return b

    def _hint(self, parent, text):
        tk.Label(parent, text=text, bg=CARD, fg=MUTED, font=("Malgun Gothic", 8),
                 justify="left", anchor="w").pack(fill="x", padx=14, pady=(0, 10))

    # -------------------------------------------------------------- Step 1
    def _step1(self, p):
        c = self._card(p, "1", "유튜브 링크 붙여넣기")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14)
        self.url_var = tk.StringVar()
        tk.Entry(row, textvariable=self.url_var, font=FONT, relief="solid",
                 bd=1).pack(fill="x", ipady=5)
        row2 = tk.Frame(c, bg=CARD)
        row2.pack(fill="x", padx=14, pady=8)
        self._btn(row2, "⬇ 다운로드", self.on_download).pack(side="left")
        self._btn(row2, "📁 영상 파일로 하기 (링크가 안 될 때)",
                  self.on_pick_video, primary=False).pack(side="left", padx=6)
        self.step1_status = tk.Label(c, text="", bg=CARD, fg=MUTED, font=FONT,
                                     anchor="w")
        self.step1_status.pack(fill="x", padx=14, pady=(0, 10))

    # -------------------------------------------------------------- Step 2
    def _step2(self, p):
        c = self._card(p, "2", "원어 자막 만들기 (무료)")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14)
        self._btn(row, "자막 만들기", self.on_transcribe).pack(side="right")
        self._hint(c, "5~10분 — 아래 로그에 '완성'이 뜬 뒤 다음 단계로 가세요")

    # -------------------------------------------------------------- Step 3
    def _step3(self, p):
        c = self._card(p, "3", "한국어 대본 만들기")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14)
        # ⭐ 앱 안에서 Claude API 로 바로 대본 생성
        self._btn(row, "🤖 대본 자동 생성(Claude)",
                  self.on_generate_script).pack(side="right")
        self._btn(row, "스크립트 복사(수동)", self.on_extract_script,
                  primary=False).pack(side="right", padx=6)
        self._hint(c, "‘자동 생성’: Claude API로 한국어 대본을 만들어 4단계에 바로 채웁니다 (설정에 API 키 필요)  ·  또는 복사해 클로드에 직접 붙여넣어도 됨")

    # -------------------------------------------------------------- Step 4
    def _step4(self, p):
        c = self._card(p, "4", "받은 대본 붙여넣기")
        self.script_text = tk.Text(c, height=7, font=FONT, relief="solid", bd=1,
                                   wrap="word")
        self.script_text.pack(fill="x", padx=14, pady=(2, 6))
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14)
        # ⭐ Vrew 없이 앱에서 바로 음성+자막 생성
        self._btn(row, "🔊 음성·자막 자동 생성",
                  self.on_auto_voice).pack(side="right")
        self._btn(row, "음성용 대본 복사(Vrew)", self.on_make_voice_script,
                  primary=False).pack(side="right", padx=6)
        self._hint(c, "‘자동 생성’: 설정의 음성(기본 TTS/내 목소리)으로 wav·srt를 바로 만들어 5단계에 채웁니다  ·  또는 대본을 복사해 Vrew로 내보내도 됨")

    # -------------------------------------------------------------- Step 5
    def _step5(self, p):
        c = self._card(p, "5", "음성·자막 파일 (자동 생성되거나 직접 선택)")
        self.file_labels = {}
        for key, label in [("wav", "5-1  음성 파일 (wav / mp3)"),
                           ("srt", "5-2  자막 파일 (srt)")]:
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT,
                     width=24, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="아직 없음", bg=CARD, fg=MUTED, font=FONT,
                           anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            self.file_labels[key] = lbl
            self._btn(row, "파일 고르기",
                      (lambda k=key, l=lbl: self.on_pick_file(k, l)),
                      primary=False).pack(side="right")
        tk.Frame(c, bg=CARD, height=8).pack()

    # -------------------------------------------------------------- Step 6
    def _step6(self, p):
        b = tk.Button(p, text="▶  6.  영상 만들기", command=self.on_build,
                      font=("Malgun Gothic", 13, "bold"), bg=BLUE, fg="white",
                      activebackground=BLUE_DARK, activeforeground="white",
                      relief="flat", bd=0, pady=14, cursor="hand2")
        b.pack(fill="x", pady=(10, 4))
        trow = tk.Frame(p, bg=BG)
        trow.pack(fill="x", pady=(0, 4))
        self._btn(trow, "🖼 썸네일만 따로 뽑기", self.on_make_thumbnail,
                  primary=False).pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._btn(trow, "🙂 영상 속 얼굴 프레임 뽑기", self.on_extract_faces,
                  primary=False).pack(side="left", expand=True, fill="x", padx=(3, 0))

    # ------------------------------------------------------------ 설정 패널
    def _settings(self, p):
        bar = tk.Frame(p, bg=BG)
        bar.pack(fill="x", pady=(6, 0))
        self.settings_open = tk.BooleanVar(value=False)
        self.settings_btn = tk.Button(
            bar, text="⚙  설정 (자막 폰트/색 · 출처 · BGM · 부분더빙)   ▼",
            command=self._toggle_settings, font=FONT, bg=BG, fg=MUTED,
            relief="flat", bd=0, anchor="w", cursor="hand2")
        self.settings_btn.pack(fill="x")

        self.settings_panel = tk.Frame(p, bg=CARD, highlightbackground=LINE,
                                       highlightthickness=1)

        def field(parent, label):
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill="x", padx=14, pady=4)
            tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT, width=16,
                     anchor="w").pack(side="left")
            return row

        sp = self.settings_panel
        # 자막
        r = field(sp, "자막 폰트/크기")
        self.sub_font = tk.StringVar(value="NanumGothic")
        tk.Entry(r, textvariable=self.sub_font, font=FONT, width=16,
                 relief="solid", bd=1).pack(side="left")
        self.sub_size = tk.IntVar(value=24)
        tk.Spinbox(r, from_=12, to=48, textvariable=self.sub_size, width=4,
                   font=FONT).pack(side="left", padx=6)
        self.sub_box = tk.BooleanVar(value=True)
        tk.Checkbutton(r, text="배경 박스", variable=self.sub_box, bg=CARD,
                       font=FONT).pack(side="left", padx=6)

        r = field(sp, "자막 색상")
        self.col_primary = self._color_pick(r, "글자", "#FFFFFF")
        self.col_outline = self._color_pick(r, "테두리", "#000000")
        self.col_back = self._color_pick(r, "배경", "#000000")

        # 출처
        r = field(sp, "출처 표시")
        self.src_text = tk.StringVar(value="")
        tk.Entry(r, textvariable=self.src_text, font=FONT, relief="solid",
                 bd=1).pack(side="left", fill="x", expand=True)
        r = field(sp, "출처 위치")
        self.src_pos = tk.StringVar(value="top-left")
        ttk.Combobox(r, textvariable=self.src_pos, width=12, state="readonly",
                     values=["top-left", "top-right", "bottom-left",
                             "bottom-right"]).pack(side="left")
        tk.Label(r, text="(비우면 원본 채널명 자동)", bg=CARD, fg=MUTED,
                 font=("Malgun Gothic", 8)).pack(side="left", padx=6)

        # 오디오 모드 (부분 더빙 포함)
        r = field(sp, "오디오")
        self.audio_mode = tk.StringVar(value="replace")
        for val, txt in [("replace", "나레이션만"),
                         ("ambience", "원본 앰비언스 깔기"),
                         ("dub", "부분더빙(원음 살리기)")]:
            tk.Radiobutton(r, text=txt, variable=self.audio_mode, value=val,
                           bg=CARD, font=FONT).pack(side="left")

        r = field(sp, "원음 유지 구간")
        self.orig_ranges = tk.StringVar(value="")
        tk.Entry(r, textvariable=self.orig_ranges, font=FONT, relief="solid",
                 bd=1).pack(side="left", fill="x", expand=True)
        tk.Label(sp, text="       예: 0:12-0:18, 1:05-1:20  (부분더빙 모드에서 이 구간은 원본 인물 목소리)",
                 bg=CARD, fg=MUTED, font=("Malgun Gothic", 8),
                 anchor="w").pack(fill="x", padx=14)

        # ---- 나레이션 음성 (TTS / 내 목소리 복제) ----
        tk.Frame(sp, bg=LINE, height=1).pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(sp, text="🔊 나레이션 음성", bg=CARD, fg=BLUE,
                 font=FONT_B, anchor="w").pack(fill="x", padx=14)

        r = field(sp, "음성 방식")
        self.voice_engine = tk.StringVar(value="edge")
        tk.Radiobutton(r, text="기본 TTS(무료)", variable=self.voice_engine,
                       value="edge", bg=CARD, font=FONT).pack(side="left")
        tk.Radiobutton(r, text="내 목소리(복제)", variable=self.voice_engine,
                       value="clone", bg=CARD, font=FONT).pack(side="left")

        r = field(sp, "TTS 목소리")
        self.tts_voice = tk.StringVar(value="ko-KR-SunHiNeural")
        ttk.Combobox(r, textvariable=self.tts_voice, width=28, state="readonly",
                     values=[f"{k}  —  {v}" for k, v in KO_VOICES.items()]
                     ).pack(side="left")
        self.tts_voice.set(f"ko-KR-SunHiNeural  —  {KO_VOICES['ko-KR-SunHiNeural']}")

        r = field(sp, "말 빠르기")
        self.tts_rate = tk.StringVar(value="+0%")
        ttk.Combobox(r, textvariable=self.tts_rate, width=8, state="readonly",
                     values=["-20%", "-10%", "+0%", "+10%", "+20%", "+30%"]
                     ).pack(side="left")

        r = field(sp, "내 음성 샘플")
        self.speaker_wav = tk.StringVar(value="")
        self.speaker_lbl = tk.Label(r, text="선택 안 됨(복제 시 필요)", bg=CARD,
                                    fg=MUTED, font=FONT, anchor="w")
        self.speaker_lbl.pack(side="left", fill="x", expand=True)
        self._btn(r, "샘플 고르기", self.on_pick_speaker,
                  primary=False).pack(side="right")
        tk.Label(sp, text="       내 목소리 복제: 6~30초 정도의 깨끗한 내 음성 wav 를 넣으면 그 목소리로 읽어줍니다 (Coqui XTTS)",
                 bg=CARD, fg=MUTED, font=("Malgun Gothic", 8),
                 anchor="w").pack(fill="x", padx=14)

        # ---- 대본 자동 생성 (Claude API) ----
        tk.Frame(sp, bg=LINE, height=1).pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(sp, text="🤖 대본 자동 생성 (Claude)", bg=CARD, fg=BLUE,
                 font=FONT_B, anchor="w").pack(fill="x", padx=14)
        r = field(sp, "API 키")
        self.api_key = tk.StringVar(value=os.environ.get("ANTHROPIC_API_KEY", ""))
        tk.Entry(r, textvariable=self.api_key, font=FONT, show="•", relief="solid",
                 bd=1).pack(side="left", fill="x", expand=True)
        r = field(sp, "모델")
        self.api_model = tk.StringVar(value=DEFAULT_MODEL)
        tk.Entry(r, textvariable=self.api_model, font=FONT, relief="solid",
                 bd=1).pack(side="left", fill="x", expand=True)
        tk.Label(sp, text="       환경변수 ANTHROPIC_API_KEY 가 있으면 비워둬도 됩니다",
                 bg=CARD, fg=MUTED, font=("Malgun Gothic", 8),
                 anchor="w").pack(fill="x", padx=14)

        # ---- 썸네일 ----
        tk.Frame(sp, bg=LINE, height=1).pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(sp, text="🖼 썸네일", bg=CARD, fg=BLUE, font=FONT_B,
                 anchor="w").pack(fill="x", padx=14)
        r = field(sp, "완성 후 생성")
        self.auto_thumb = tk.BooleanVar(value=True)
        tk.Checkbutton(r, text="영상 완성 시 썸네일·대표프레임 자동 생성",
                       variable=self.auto_thumb, bg=CARD, font=FONT).pack(side="left")
        r = field(sp, "썸네일 제목")
        self.thumb_title = tk.StringVar(value="")
        tk.Entry(r, textvariable=self.thumb_title, font=FONT, relief="solid",
                 bd=1).pack(side="left", fill="x", expand=True)
        tk.Label(sp, text="       비우면 영상 제목을 사용합니다",
                 bg=CARD, fg=MUTED, font=("Malgun Gothic", 8),
                 anchor="w").pack(fill="x", padx=14)

        r = field(sp, "인물 얼굴 사진")
        self.face_image = tk.StringVar(value="")
        self.face_lbl = tk.Label(r, text="선택 안 됨(있으면 오른쪽에 합성)", bg=CARD,
                                 fg=MUTED, font=FONT, anchor="w")
        self.face_lbl.pack(side="left", fill="x", expand=True)
        self._btn(r, "사진 고르기", self.on_pick_face,
                  primary=False).pack(side="right")
        r = field(sp, "영상 속 얼굴")
        self.pick_face = tk.BooleanVar(value=True)
        tk.Checkbutton(r, text="사진이 없으면 영상에서 얼굴 프레임 자동 선택",
                       variable=self.pick_face, bg=CARD, font=FONT).pack(side="left")
        tk.Label(sp, text="       썸네일엔 얼굴을 넣는 게 좋아요: 사진을 고르거나, 영상 속 얼굴을 자동으로 씁니다",
                 bg=CARD, fg=MUTED, font=("Malgun Gothic", 8),
                 anchor="w").pack(fill="x", padx=14)

        tk.Frame(sp, bg=LINE, height=1).pack(fill="x", padx=14, pady=(8, 4))
        r = field(sp, "기타")
        self.remove_bgm = tk.BooleanVar(value=False)
        tk.Checkbutton(r, text="원본 BGM 제거(demucs, 앰비언스/부분더빙 시)",
                       variable=self.remove_bgm, bg=CARD, font=FONT).pack(side="left")
        tk.Frame(sp, bg=CARD, height=8).pack()

    def _color_pick(self, parent, label, default):
        var = tk.StringVar(value=default)
        tk.Label(parent, text=label, bg=CARD, fg=MUTED, font=FONT).pack(side="left")
        sw = tk.Label(parent, text="  ", bg=default, relief="solid", bd=1)
        sw.pack(side="left", padx=(2, 8))

        def pick():
            c = colorchooser.askcolor(color=var.get())[1]
            if c:
                var.set(c)
                sw.configure(bg=c)
        sw.bind("<Button-1>", lambda e: pick())
        return var

    def _toggle_settings(self):
        if self.settings_open.get():
            self.settings_panel.pack_forget()
            self.settings_btn.configure(text=self.settings_btn.cget("text")[:-1] + "▼")
        else:
            self.settings_panel.pack(fill="x", after=self.settings_btn.master)
            self.settings_btn.configure(text=self.settings_btn.cget("text")[:-1] + "▲")
        self.settings_open.set(not self.settings_open.get())

    # ------------------------------------------------------------- 로그창
    def _logbox(self, p):
        c = tk.Frame(p, bg="#0d1017")
        c.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(c, height=10, bg="#0d1017", fg="#cdd6e4",
                           font=("Consolas", 9), relief="flat", wrap="word",
                           state="disabled")
        self.log.pack(fill="both", expand=True, padx=2, pady=2)

    # ============================================================== 로깅/스레드
    def log_msg(self, msg: str):
        self.log_q.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _run_bg(self, fn):
        threading.Thread(target=self._guard(fn), daemon=True).start()

    def _guard(self, fn):
        def wrapped():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                self.log_msg(f"[오류] {exc}")
        return wrapped

    # ============================================================== 동작들
    def on_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("알림", "유튜브 링크를 입력하세요.")
            return
        self.step1_status.configure(text="다운로드 중...")
        self.log_msg(f"[*] 다운로드: {url}")

        def work():
            try:
                info = self.downloader.get_info(url)
                self.channel_name = info.uploader
                self.video_title = info.title
                self.log_msg(f"    제목: {info.title} / {info.duration_str}")
            except Exception as exc:  # noqa: BLE001
                self.log_msg(f"    (정보 조회 건너뜀: {exc})")
            path = self.downloader.download(url)
            self.video_path = path
            self.log_msg(f"[+] 저장됨: {os.path.basename(path)}")
            self.step1_status.configure(text=f"완료: {os.path.basename(path)}")
        self._run_bg(work)

    def on_pick_video(self):
        path = filedialog.askopenfilename(
            title="영상 파일 선택",
            filetypes=[("영상", "*.mp4 *.mkv *.webm *.mov *.avi"), ("모든 파일", "*.*")])
        if path:
            self.video_path = path
            self.step1_status.configure(text=f"파일: {os.path.basename(path)}")
            self.log_msg(f"[+] 영상 파일 선택: {path}")

    def on_transcribe(self):
        if not self.video_path:
            messagebox.showwarning("알림", "먼저 영상을 다운로드하거나 파일을 선택하세요.")
            return
        self.log_msg("원어 음성인식 시작 — 20분 영상 기준 5~10분 걸려요")

        def work():
            tr = Transcriber(model_size="small")
            result = tr.transcribe(self.video_path, log=self.log_msg)
            self.transcript = result
            base = os.path.splitext(os.path.basename(self.video_path))[0]
            self.orig_srt = os.path.join(DOWNLOAD_DIR, base + ".orig.srt")
            with open(self.orig_srt, "w", encoding="utf-8") as f:
                f.write(result.to_srt())
            self.log_msg(f"완성 ✔  원어 자막 {result.sentence_count}문장 → {os.path.basename(self.orig_srt)}")
            self.log_msg("이제 [스크립트 뽑기]를 눌러 대본을 만드세요")
        self._run_bg(work)

    def on_extract_script(self):
        if not self.transcript:
            messagebox.showwarning("알림", "먼저 2단계(자막 만들기)를 완료하세요.")
            return
        title = ""
        prompt = script_tools.build_claude_prompt(self.transcript.to_text(), title)
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        path = os.path.join(DOWNLOAD_DIR, "claude_prompt.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(prompt)
        self.log_msg("[+] 대본용 스크립트 자동 복사됨 → 클로드(대본생성기)에 붙여넣으세요")
        self.log_msg(f"    (백업 저장: {os.path.basename(path)})")

    def on_generate_script(self):
        if not self.transcript:
            messagebox.showwarning("알림", "먼저 2단계(자막 만들기)를 완료하세요.")
            return
        key = self.api_key.get().strip() or None
        model = self.api_model.get().strip() or DEFAULT_MODEL
        self.log_msg("─" * 40)
        self.log_msg("[3] Claude로 한국어 대본 생성 중...")

        def work():
            script = generate_korean_script(
                self.transcript.to_text(), title=self.video_title,
                model=model, api_key=key, log=self.log_msg)
            # 4단계 텍스트박스에 채워넣기
            self.script_text.delete("1.0", "end")
            self.script_text.insert("1.0", script)
            n = len([x for x in script.split("\n") if x.strip()])
            self.log_msg(f"✔ 대본 {n}문장 생성 → 4단계에 채웠습니다. 이제 [음성·자막 자동 생성]으로 진행하세요")
        self._run_bg(work)

    def on_make_thumbnail(self):
        video = self.last_output or self.video_path
        if not video or not os.path.exists(video):
            messagebox.showwarning("알림", "먼저 영상을 만들거나 불러오세요.")
            return
        self._run_bg(lambda: self._do_thumbnail(video))

    def on_pick_face(self):
        path = filedialog.askopenfilename(
            title="썸네일에 넣을 인물 얼굴 사진",
            filetypes=[("이미지", "*.png *.jpg *.jpeg *.webp"), ("모든 파일", "*.*")])
        if path:
            self.face_image.set(path)
            self.face_lbl.configure(text=os.path.basename(path), fg=TEXT)

    def on_extract_faces(self):
        video = self.last_output or self.video_path
        if not video or not os.path.exists(video):
            messagebox.showwarning("알림", "먼저 영상을 만들거나 불러오세요.")
            return

        def work():
            self.log_msg("🙂 영상에서 얼굴 프레임 찾는 중...")
            shots = extract_face_shots(video, DOWNLOAD_DIR, count=5, log=self.log_msg)
            if shots:
                self.log_msg(f"✔ 얼굴 프레임 {len(shots)}장: face_shot_1~{len(shots)}.jpg "
                             "(마음에 드는 걸 인물 사진으로 골라도 됩니다)")
        self._run_bg(work)

    def _do_thumbnail(self, video: str):
        title = self.thumb_title.get().strip() or self.video_title
        face = self.face_image.get().strip() or None
        self.log_msg("🖼 썸네일 생성 중...")
        extract_candidates(video, DOWNLOAD_DIR, count=5, log=self.log_msg)
        out = os.path.join(DOWNLOAD_DIR, "thumbnail.jpg")
        make_thumbnail(video, out, title=title, face_image=face,
                       pick_face=(face is None and self.pick_face.get()),
                       log=self.log_msg)
        self.log_msg(f"✔ 썸네일: {out}  (대표 프레임 후보: thumb_cand_1~5.jpg)")

    def on_make_voice_script(self):
        script = self.script_text.get("1.0", "end").strip()
        if not script:
            messagebox.showwarning("알림", "받은 대본을 붙여넣으세요.")
            return
        vrew = script_tools.format_for_vrew(script)
        self.root.clipboard_clear()
        self.root.clipboard_append(vrew)
        path = os.path.join(DOWNLOAD_DIR, "vrew_script.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(vrew)
        n = len([x for x in vrew.split("\n") if x.strip()])
        self.log_msg(f"[+] 음성용 대본 {n}문장 복사됨 → Vrew에 붙여 음성(wav)·자막(srt)을 내보내세요")

    def on_pick_speaker(self):
        path = filedialog.askopenfilename(
            title="내 목소리 샘플 (wav, 6~30초)",
            filetypes=[("음성", "*.wav *.mp3 *.m4a"), ("모든 파일", "*.*")])
        if path:
            self.speaker_wav.set(path)
            self.speaker_lbl.configure(text=os.path.basename(path), fg=TEXT)

    def _make_engine(self):
        if self.voice_engine.get() == "clone":
            spk = self.speaker_wav.get().strip()
            if not spk:
                raise RuntimeError("‘내 목소리(복제)’ 방식은 설정에서 음성 샘플을 먼저 골라주세요.")
            self.log_msg("  음성 엔진: 내 목소리 복제(Coqui XTTS)")
            return CloneEngine(speaker_wav=spk, language="ko")
        voice = self.tts_voice.get().split("  —  ")[0].strip()
        self.log_msg(f"  음성 엔진: 기본 TTS ({voice}, {self.tts_rate.get()})")
        return EdgeEngine(voice=voice, rate=self.tts_rate.get())

    def on_auto_voice(self):
        script = self.script_text.get("1.0", "end").strip()
        if not script:
            messagebox.showwarning("알림", "받은 대본을 붙여넣으세요.")
            return
        self.log_msg("─" * 40)
        self.log_msg("[4.5] 음성·자막 자동 생성 중...")

        def work():
            engine = self._make_engine()
            wav = os.path.join(DOWNLOAD_DIR, "narration.wav")
            srt = os.path.join(DOWNLOAD_DIR, "narration.srt")
            synthesize_script(script, engine, wav, srt, gap=0.35, log=self.log_msg)
            self.wav_path, self.srt_path = wav, srt
            self.file_labels["wav"].configure(text=os.path.basename(wav), fg=TEXT)
            self.file_labels["srt"].configure(text=os.path.basename(srt), fg=TEXT)
            self.log_msg("✔ 음성(wav)·자막(srt) 완성 → 바로 [6. 영상 만들기] 가능")
        self._run_bg(work)

    def on_pick_file(self, kind: str, label: tk.Label):
        ft = [("음성", "*.wav *.mp3 *.m4a")] if kind == "wav" else [("자막", "*.srt")]
        path = filedialog.askopenfilename(title="파일 선택", filetypes=ft + [("모든 파일", "*.*")])
        if not path:
            return
        if kind == "wav":
            self.wav_path = path
        else:
            self.srt_path = path
        label.configure(text=os.path.basename(path), fg=TEXT)
        self.log_msg(f"[+] {kind} 선택: {os.path.basename(path)}")

    def _parse_ranges(self, text: str):
        ranges = []
        for chunk in text.replace(",", " ").split():
            if "-" not in chunk:
                continue
            a, b = chunk.split("-", 1)
            try:
                ranges.append((parse_time(a), parse_time(b)))
            except Exception:  # noqa: BLE001
                self.log_msg(f"  · 구간 해석 실패: {chunk}")
        return ranges

    def on_build(self):
        if not self.video_path:
            messagebox.showwarning("알림", "영상이 없습니다. 1단계를 먼저 하세요.")
            return
        if not self.wav_path:
            messagebox.showwarning("알림", "Vrew 음성(wav) 파일을 5단계에서 선택하세요.")
            return

        src_text = self.src_text.get().strip() or (
            f"출처: {self.channel_name}" if self.channel_name else "")
        opt = AssembleOptions(
            subtitle=SubStyle(
                font=self.sub_font.get(), fontsize=self.sub_size.get(),
                primary=self.col_primary.get(), outline=self.col_outline.get(),
                back=self.col_back.get(), box=self.sub_box.get()),
            source=SourceMark(text=src_text, position=self.src_pos.get()),
            audio_mode=self.audio_mode.get(),
            original_segments=self._parse_ranges(self.orig_ranges.get()),
            remove_original_bgm=self.remove_bgm.get(),
        )
        srt = self.srt_path
        out = os.path.join(DOWNLOAD_DIR, "완성본.mp4")
        self.log_msg("─" * 40)
        self.log_msg("[6] 영상 만들기 시작...")
        if opt.audio_mode == "dub":
            self.log_msg(f"    부분더빙: 원음 구간 {len(opt.original_segments)}개")

        def work():
            result = build_video(self.video_path, self.wav_path, srt, out, opt,
                                 log=self.log_msg)
            self.last_output = result
            self.log_msg(f"🎉 완성! → {result}")
            if self.auto_thumb.get():
                try:
                    self._do_thumbnail(result)
                except Exception as exc:  # noqa: BLE001
                    self.log_msg(f"  · 썸네일 생성 건너뜀: {exc}")
            messagebox.showinfo("완성", f"영상이 만들어졌어요:\n{result}")
        self._run_bg(work)


def main():
    root = tk.Tk()
    AutoEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
