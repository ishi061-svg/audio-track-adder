# 音声トラック追加アプリ
# ステップ2：画面を付ける
#   「MP4 を選ぶ」「MP3 を追加」「合成する」のボタンで使えるようにする
#   合成そのものは add_audio.py の係にまかせる（画面と合成の仕事を分ける）
#   画面にファイルをドラッグ＆ドロップしても入れられる（.mp4 と .mp3 を自動で振り分ける）
# 追加：MP3 を最大4つまで一覧に入れ、トラック2〜5にする。「上へ」「下へ」「外す」で並びを直せる
# 追加：合成中の進み具合を、棒と%で表示する
# 追加：MP3 のほかに、M4A と WAV も入れられるようにする
# 追加：元の音の扱い方を、3つから1つ選べるようにする
#       足す（元の音はトラック1のまま）／入れ替える（元の音はトラック2へ）／上書きする（元の音は消す）
# 追加：見た目を整える
#       ①動画 ②音声 ③元の音 の順に、白いカードに分けて並べ、上から順に操作すれば終わるようにした
#       色・文字の大きさ・余白は、下の「見た目の決まり」の1か所で決める
#
# 動かし方：python app.py
# 必要な部品：tkinterdnd2（ドラッグ＆ドロップを受け取るため。入れ方：python -m pip install tkinterdnd2）

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk  # ttk：進み具合の棒（Progressbar）など、tkinter の追加の部品

from tkinterdnd2 import DND_FILES, TkinterDnD

from add_audio import (ADD, AUDIO_SUFFIXES, LAST_TRACK, MAX_ADDED, ORIGINAL, OVERWRITE, SWAP, add_audio_tracks,
                       count_streams, make_output_path, track_order)

# 元の音の扱い方の選び方（画面に出す文と、add_audio に渡す印）
MODES = [
    ("足す（元の音はトラック1のまま）", ADD),
    ("入れ替える（元の音はトラック2へ）", SWAP),
    ("上書きする（元の音は消す）", OVERWRITE),
]

# ファイルを選ぶ画面で使う、拡張子の書き方（例：「*.mp3 *.m4a *.wav」）
AUDIO_PATTERNS = " ".join("*" + suffix for suffix in AUDIO_SUFFIXES)
# 画面に出す、使える形式の名前（例：「MP3・M4A・WAV」）
AUDIO_NAMES = "・".join(suffix[1:].upper() for suffix in AUDIO_SUFFIXES)

# ---------- 見た目の決まり（色・文字・余白は、ここだけで決める） ----------
BG = "#f3f4f6"           # 画面の地の色（うすい灰色）
CARD = "#ffffff"         # カードの色（白）
BORDER = "#dfe2e7"       # カードのふちの色
TEXT = "#1f2937"         # ふつうの文字（黒に近い紺）
SUB = "#6b7280"          # 補足の文字（灰色）
ACCENT = "#2563eb"       # 大事なボタンの色（青）
ACCENT_HOVER = "#1d4ed8" # 大事なボタンに、マウスが乗ったときの色
BUTTON = "#eef0f3"       # ふつうのボタンの色
BUTTON_HOVER = "#e2e5ea" # ふつうのボタンに、マウスが乗ったときの色
DISABLED = "#c9cdd4"     # 押せないボタンの色
SELECT = "#dbe7fe"       # 一覧で選んだ行の色（うすい青）
OK = "#15803d"           # できたときの文字（緑）
NG = "#b91c1c"           # 失敗したときの文字（赤）

FONT_NAME = "Yu Gothic UI"   # Windows に入っている、読みやすい日本語の文字
FONT = (FONT_NAME, 10)
FONT_BOLD = (FONT_NAME, 10, "bold")
FONT_SMALL = (FONT_NAME, 9)
FONT_TITLE = (FONT_NAME, 14, "bold")
MARK_OK = "✓ "   # できたときの印。  は「改行しない空白」（印のすぐ後ろで改行されないように）
MARK_NG = "✕ "   # 失敗したときの印
FONT_BIG = (FONT_NAME, 11, "bold")

CONTENT_WIDTH = 460  # カードの中身の幅（ピクセル）。長い名前が入っても、画面はこれ以上広がらない
DROP_HEIGHT = 50     # ドラッグ＆ドロップの場所の高さ（ピクセル）
DROP_ACTIVE = "#e0ebff"  # ファイルを持って画面に来たときの、ドロップの場所の色（うすい青）
FONT_ICON = (FONT_NAME, 14)  # ドロップの場所の矢印


def shorten(name, font, max_width):
    """長いファイル名を、まん中を「…」にして、max_width（ピクセル）に収まるように縮める
    最後の拡張子が見えるように、後ろも残す。日本語のように幅の広い文字でも、実際の幅で測るので、はみ出さない
    例：「とても長い名前のファイル.mp3」→「とても長い…ファイル.mp3」"""
    if font.measure(name) <= max_width:
        return name
    head, tail = name[: len(name) // 2], name[len(name) // 2:]
    # 前と後ろから1文字ずつ削って、収まるまで縮める（後ろは拡張子が残るよう、前を多めに削る）
    while head or tail:
        if len(head) >= len(tail) - 4 and head:
            head = head[:-1]
        else:
            tail = tail[1:]
        if font.measure(head + "…" + tail) <= max_width:
            return head + "…" + tail
    return "…"


class App:
    def __init__(self, root):
        self.root = root
        self.video_path = None  # 選んだ MP4
        self.video_has_original = True  # 選んだ MP4 に、元の音が入っているか（トラック番号の表示に使う）
        self.audio_paths = []   # 選んだ音の一覧（ふだんは、並んでいる順にトラック2・3・4・5 になる）
        self.mode = tk.StringVar(value=ADD)  # 元の音の扱い方（ADD・SWAP・OVERWRITE のどれか）
        # 合成は別の流れ（スレッド）で動かすので、終わったことを画面に伝えるための受け渡し場所
        self.results = queue.Queue()
        self.font = tkfont.Font(root, font=FONT)  # ファイル名の幅を測るための文字
        self.leave_job = None  # ドロップの場所を白に戻す予定（ドラッグ中のちらつきを防ぐため）

        root.title("音声トラック追加")
        root.resizable(False, False)
        root.configure(bg=BG)

        page = tk.Frame(root, bg=BG, padx=18, pady=12)
        page.pack()

        # 見出し（説明は、意味の切れ目で自分で改行する。自動の折り返しだと、空白のところで変に切れるため）
        tk.Label(page, text="音声トラック追加", font=FONT_TITLE, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(page, text=f"MP4 に、選んだ音（{AUDIO_NAMES}）を別のトラックとして入れます",
                 font=FONT_SMALL, bg=BG, fg=SUB, justify="left").pack(anchor="w", pady=(0, 8))

        # ドラッグ＆ドロップの場所（点線のわく）。ファイルを持って画面に来ると、青くなって知らせる
        # 実際は画面のどこに落としても入るが、「ここに落とせる」と目で分かるように場所を見せる
        self.drop_zone = tk.Canvas(page, width=CONTENT_WIDTH + 30, height=DROP_HEIGHT, bg=BG, highlightthickness=0)
        self.drop_zone.pack(pady=(0, 8))
        self.draw_drop_zone(active=False)

        # ① 動画
        card = self.make_card(page, "① 動画（MP4）")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        self.make_button(row, "選ぶ…", self.choose_video).pack(side="left")
        self.video_label = tk.Label(row, text="まだ選んでいません（ドラッグ＆ドロップでも入れられます）",
                                    font=FONT, bg=CARD, fg=SUB, anchor="w")
        self.video_label.pack(side="left", padx=(10, 0))

        # ② 音声
        card = self.make_card(page, f"② 音声（{MAX_ADDED}つまで）")
        self.audio_list = tk.Listbox(
            card, height=MAX_ADDED, font=FONT, activestyle="none", exportselection=False,
            relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            bg=CARD, fg=TEXT, selectbackground=SELECT, selectforeground=TEXT,
        )
        self.audio_list.pack(fill="x")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        self.make_button(row, "追加…", self.choose_audio).pack(side="left")
        self.make_button(row, "外す", self.remove_audio).pack(side="right")
        self.make_button(row, "下へ", lambda: self.move_audio(1)).pack(side="right", padx=(0, 6))
        self.make_button(row, "上へ", lambda: self.move_audio(-1)).pack(side="right", padx=(0, 6))

        # ③ 元の音（3つから1つ選ぶ。変えると、一覧のトラック番号をすぐに書き直す）
        card = self.make_card(page, "③ 元の音")
        for text, value in MODES:
            tk.Radiobutton(card, text=text, value=value, variable=self.mode, command=self.on_mode_changed,
                           font=FONT, bg=CARD, fg=TEXT, activebackground=CARD, selectcolor=CARD,
                           highlightthickness=0, cursor="hand2").pack(anchor="w")

        # 保存先（MP4 を選ぶと表示する）。長くなりやすいので、カードの幅で折り返す（幅は下で決める）
        self.output_label = tk.Label(page, text="", font=FONT_SMALL, bg=BG, fg=SUB, anchor="w", justify="left")
        self.output_label.pack(anchor="w")

        # 合成するボタン（MP4 と音を1つ以上選ぶまでは押せない）。いちばん大事なので、大きく青くする
        self.merge_button = self.make_button(page, "合成する", self.start_merge, primary=True)
        self.merge_button.pack(fill="x", pady=(8, 0))

        # 進み具合の棒（0〜100）
        style = ttk.Style(root)
        style.theme_use("clam")  # 色を変えられる見た目にする（Windows ふうの見た目だと、棒の色を変えられない）
        style.configure("Accent.Horizontal.TProgressbar", troughcolor=BORDER, background=ACCENT,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
        self.progress = ttk.Progressbar(page, maximum=100, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(8, 0))

        # 結果の表示
        self.status_label = tk.Label(page, text="", font=FONT_SMALL, bg=BG, fg=TEXT, anchor="w", justify="left")
        self.status_label.pack(anchor="w", pady=(4, 0))

        self.refresh_audio_list()
        self.update_button()

        # 保存先と結果は、カードの幅で折り返す（それより広いと、長い名前のときに画面が横に広がってしまう）
        root.update_idletasks()
        # card.master は、カードの外わく。画面に出る前なので、「出したい幅」（reqwidth）で測る
        # 文字のまわりにも少し余白が付くので、その分（12ピクセル）を引いておく
        wrap = card.master.winfo_reqwidth() - 12
        self.output_label.config(wraplength=wrap)
        self.status_label.config(wraplength=wrap)

        # 画面のどこに落としても受け取れるように、画面とその中の部品すべてを「落とし先」にする
        self.register_drop(root)

    # ---------- 見た目の部品 ----------

    def make_card(self, parent, title):
        """見出しつきの白いカードを作り、中身を入れる場所を返す"""
        outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=14, pady=8)
        outer.pack(fill="x", pady=(0, 8))
        tk.Label(outer, text=title, font=FONT_BOLD, bg=CARD, fg=TEXT).pack(anchor="w", pady=(0, 4))
        # 中身の幅を CONTENT_WIDTH に固定する（長い名前が入っても、カードが広がらないように）
        body = tk.Frame(outer, bg=CARD, width=CONTENT_WIDTH)
        body.pack(fill="x")
        tk.Frame(outer, bg=CARD, width=CONTENT_WIDTH, height=0).pack()
        return body

    def make_button(self, parent, text, command, primary=False):
        """平らなボタンを作る。マウスが乗ると、少し色が濃くなる
        primary=True は「合成する」用の、大きな青いボタン"""
        if primary:
            colors = (ACCENT, ACCENT_HOVER, "white")
            button = tk.Button(parent, text=text, command=command, font=FONT_BIG, pady=6)
        else:
            colors = (BUTTON, BUTTON_HOVER, TEXT)
            button = tk.Button(parent, text=text, command=command, font=FONT, padx=12, pady=2)
        normal, hover, fg = colors
        button.config(bg=normal, fg=fg, activebackground=hover, activeforeground=fg, relief="flat", bd=0,
                      cursor="hand2", disabledforeground="white" if primary else SUB)
        button.colors = colors
        button.bind("<Enter>", lambda e: button["state"] == "normal" and button.config(bg=hover))
        button.bind("<Leave>", lambda e: button["state"] == "normal" and button.config(bg=normal))
        return button

    def set_enabled(self, button, enabled):
        """ボタンを押せる・押せないにする。押せないときは、灰色にして分かるようにする"""
        normal = button.colors[0]
        button.config(state="normal" if enabled else "disabled", bg=normal if enabled else DISABLED,
                      cursor="hand2" if enabled else "arrow")

    # ---------- ドラッグ＆ドロップ ----------

    def draw_drop_zone(self, active):
        """ドロップの場所を描く。active=True は、ファイルを持って画面に来ているとき（青くする）"""
        c = self.drop_zone
        c.delete("all")
        w, h = CONTENT_WIDTH + 30, DROP_HEIGHT
        fill, line = (DROP_ACTIVE, ACCENT) if active else (CARD, "#b6bcc6")
        c.create_rectangle(1, 1, w - 2, h - 2, fill=fill, outline=line, width=2, dash=(6, 4))
        text = "はなすと入ります" if active else "ここに MP4 と音声ファイルをドラッグ＆ドロップ（まとめてでもOK）"
        c.create_text(w // 2, h // 2, text="⬇  " + text, font=FONT_BOLD if active else FONT,
                      fill=ACCENT if active else SUB)

    def register_drop(self, widget):
        """widget とその中の部品すべてで、ドラッグ＆ドロップを受け取れるようにする"""
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self.on_drop)
        widget.dnd_bind("<<DropEnter>>", self.on_drag_enter)  # ファイルを持って、画面の上に来た
        widget.dnd_bind("<<DropLeave>>", self.on_drag_leave)  # 画面の外に出た（落とさずにやめた）
        for child in widget.winfo_children():
            self.register_drop(child)

    def on_drag_enter(self, event):
        """ファイルを持って画面に来たとき：ドロップの場所を青くする"""
        if self.leave_job:  # 部品から部品へ動いただけなら、白に戻す予定を取り消す
            self.root.after_cancel(self.leave_job)
            self.leave_job = None
        self.draw_drop_zone(active=True)
        return event.action

    def on_drag_leave(self, event):
        """画面の外に出たとき：ドロップの場所を白に戻す
        画面の中で部品から部品へ動いたときも「出た」と知らされるので、少し待ってから戻す（ちらつかないように）"""
        self.leave_job = self.root.after(80, self.end_drag)
        return event.action

    def end_drag(self):
        self.leave_job = None
        self.draw_drop_zone(active=False)

    def on_drop(self, event):
        """ファイルが落とされたとき：拡張子を見て、MP4 の欄と音の一覧に振り分ける"""
        self.end_drag()
        # 落とされたファイルの一覧は1つの文字列で届く。空白を含む名前は { } で囲まれているので、splitlist で分ける
        paths = [Path(p) for p in self.root.tk.splitlist(event.data)]
        audios = []
        unknown = []
        for path in paths:
            suffix = path.suffix.lower()  # 拡張子（.MP4 のような大文字も小文字にそろえる）
            if suffix == ".mp4":
                self.set_video(path)
            elif suffix in AUDIO_SUFFIXES:
                audios.append(path)
            else:
                unknown.append(path.name)

        # まとめて落とされた音は、ファイル名の順に並べて足す
        # （Windows がファイルを渡す順番は、選び方によって変わることがあるため）
        audios.sort(key=lambda p: p.name)
        if audios:
            self.add_audios(audios)
        if unknown:
            self.show_error(f"MP4 か {AUDIO_NAMES} を入れてください：" + "、".join(unknown))
        return event.action

    # ---------- ファイルを選ぶ ----------

    def choose_video(self):
        path = filedialog.askopenfilename(title="MP4 を選ぶ", filetypes=[("MP4 動画", "*.mp4"), ("すべてのファイル", "*.*")])
        if path:  # 「キャンセル」を押したときは何もしない
            self.set_video(Path(path))

    def choose_audio(self):
        # askopenfilenames（最後に s）は、まとめて何個か選べる
        paths = filedialog.askopenfilenames(title="音声を追加",
                                            filetypes=[(f"音声（{AUDIO_NAMES}）", AUDIO_PATTERNS), ("すべてのファイル", "*.*")])
        if paths:
            self.add_audios([Path(p) for p in paths])

    def set_video(self, path):
        """MP4 を決める（ボタンで選んだときも、ドロップしたときも、ここを通る）"""
        self.video_path = path
        # 「選ぶ…」ボタンの右に収まる幅で、名前を縮める
        self.video_label.config(text=shorten(path.name, self.font, CONTENT_WIDTH - 90), fg=TEXT)
        self.output_label.config(text=f"保存先：{make_output_path(path)}")
        # 元の音が入っているかを調べて、一覧のトラック番号を合わせる
        # （読めないファイルや ffmpeg がないときは「入っている」としておく。くわしい理由は合成するときに出る）
        try:
            self.video_has_original = count_streams(path, "a") != 0
        except RuntimeError:
            self.video_has_original = True
        self.refresh_audio_list(select=self.selected_index())
        self.update_button()

    def add_audios(self, paths):
        """音を一覧の最後に足す。入りきらない分は足さずに知らせる"""
        room = MAX_ADDED - len(self.audio_paths)  # あと何個入るか
        self.audio_paths += paths[:room]
        self.refresh_audio_list()
        self.update_button()
        left_out = paths[room:]
        if left_out:
            self.show_error(f"音のファイルは{MAX_ADDED}つまでです（トラック{LAST_TRACK}まで）。入らなかったもの："
                            + "、".join(p.name for p in left_out))

    def on_mode_changed(self):
        """元の音の扱い方を変えたとき：一覧のトラック番号を書き直す"""
        self.refresh_audio_list(select=self.selected_index())
        self.status_label.config(text="")

    # ---------- 一覧の並びを直す ----------

    def selected_index(self):
        """一覧で選ばれている行の番号を返す（選ばれていなければ None）"""
        if not self.audio_paths:  # 「まだ選んでいません」の行は、選んだことにしない
            return None
        selection = self.audio_list.curselection()
        return selection[0] if selection else None

    def move_audio(self, step):
        """選ばれている音を、step が -1 なら1つ上へ、1 なら1つ下へ動かす"""
        index = self.selected_index()
        if index is None:
            return
        new_index = index + step
        if not 0 <= new_index < len(self.audio_paths):  # いちばん上・いちばん下より外には動かさない
            return
        paths = self.audio_paths
        paths[index], paths[new_index] = paths[new_index], paths[index]  # 入れ替える
        self.refresh_audio_list(select=new_index)

    def remove_audio(self):
        """選ばれている音を一覧から外す（ファイルそのものは消さない）"""
        index = self.selected_index()
        if index is None:
            return
        del self.audio_paths[index]
        self.refresh_audio_list(select=min(index, len(self.audio_paths) - 1))
        self.update_button()

    def refresh_audio_list(self, select=None):
        """一覧の表示を、今の audio_paths に合わせて書き直す
        トラック番号は、合成と同じ track_order で決める（画面と、できあがる動画の番号がずれないように）"""
        order = track_order(len(self.audio_paths), self.video_has_original, self.mode.get())
        # 選んだ音の番号 → トラック番号（1 から）
        track_of = {source: track for track, source in enumerate(order, start=1) if source != ORIGINAL}
        self.audio_list.delete(0, "end")
        for index, path in enumerate(self.audio_paths):
            label = f"  トラック{track_of[index]}　"
            name = shorten(path.name, self.font, CONTENT_WIDTH - self.font.measure(label) - 30)
            self.audio_list.insert("end", label + name)
        if not self.audio_paths:
            self.audio_list.insert("end", "  まだ選んでいません（ドラッグ＆ドロップか「追加…」で入れる）")
            self.audio_list.itemconfig(0, fg=SUB, selectbackground=CARD, selectforeground=SUB)
        elif select is not None and select >= 0:
            self.audio_list.selection_set(select)

    # ---------- 合成 ----------

    def update_button(self):
        """MP4 と音（1つ以上）がそろっていれば「合成する」を押せるようにする"""
        ready = self.video_path is not None and len(self.audio_paths) > 0
        self.set_enabled(self.merge_button, ready)
        self.status_label.config(text="")

    def show_error(self, message):
        self.status_label.config(text=MARK_NG + message, fg=NG)

    def start_merge(self):
        """合成を始める
        合成中も画面が固まらないように、合成は別の流れ（スレッド）で動かす"""
        # 合成中に一覧が変えられても混ざらないように、今の選択を写し取っておく
        video_path = self.video_path
        audio_paths = list(self.audio_paths)
        mode = self.mode.get()
        output_path = make_output_path(video_path)
        self.set_enabled(self.merge_button, False)
        self.merge_button.config(text="合成しています…")
        self.progress.config(value=0)
        self.status_label.config(text="合成しています… 0%", fg=TEXT)

        def report(percent):
            """合成の流れから、進み具合を受け渡し場所に入れる（画面の部品には、ここから直接触らない）"""
            self.results.put(("progress", percent))

        def work():
            try:
                add_audio_tracks(video_path, audio_paths, output_path, on_progress=report,
                                 mode=mode)
                self.results.put(("ok", f"できました：{output_path}"))
            except RuntimeError as error:  # 考えておいた失敗（理由が書いてある）
                self.results.put(("ng", str(error)))
            except Exception as error:  # 考えていなかった失敗でも、画面が「合成しています…」のまま止まらないようにする
                self.results.put(("ng", f"思わぬエラーで止まりました：{error}"))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self.check_result)

    def check_result(self):
        """受け渡し場所を 0.1秒ごとに見て、進み具合や結果を画面に出す
        （画面の部品は、画面の流れからしか触れないので、受け渡し場所を見に行く）"""
        while True:
            try:
                kind, value = self.results.get_nowait()
            except queue.Empty:
                self.root.after(100, self.check_result)  # まだ終わっていなければ、また 0.1秒後に見る
                return

            if kind == "progress":  # 進み具合：棒と%を更新して、次を見る
                self.progress.config(value=value)
                self.status_label.config(text=f"合成しています… {value:.0f}%")
                continue

            # 終わった（成功・失敗）
            if kind == "ok":
                self.progress.config(value=100)
                self.status_label.config(text=MARK_OK + value, fg=OK)
            else:
                self.progress.config(value=0)  # 失敗したときは、棒を空に戻す
                self.status_label.config(text=MARK_NG + value, fg=NG)
            self.merge_button.config(text="合成する")
            self.set_enabled(self.merge_button, True)
            return


def main():
    root = TkinterDnD.Tk()  # ドラッグ＆ドロップを受け取れる画面
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
