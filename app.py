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
#
# 動かし方：python app.py
# 必要な部品：tkinterdnd2（ドラッグ＆ドロップを受け取るため。入れ方：python -m pip install tkinterdnd2）

import queue
import threading
import tkinter as tk
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

NAME_LIMIT = 36  # 画面に出すファイル名の、いちばん長い文字数（これより長い名前は、まん中を「…」で縮める）


def shorten(name, limit=NAME_LIMIT):
    """長いファイル名を、まん中を「…」にして縮める（最後の拡張子が見えるように、後ろも残す）
    例：「とても長い名前のファイル.mp3」→「とても長い…ファイル.mp3」"""
    if len(name) <= limit:
        return name
    tail = 12                     # 後ろに残す文字数
    head = limit - tail - 1       # 前に残す文字数（「…」の1文字分を引く）
    return name[:head] + "…" + name[-tail:]


class App:
    def __init__(self, root):
        self.root = root
        self.video_path = None  # 選んだ MP4
        self.video_has_original = True  # 選んだ MP4 に、元の音が入っているか（トラック番号の表示に使う）
        self.audio_paths = []   # 選んだ音の一覧（ふだんは、並んでいる順にトラック2・3・4・5 になる）
        self.mode = tk.StringVar(value=ADD)  # 元の音の扱い方（ADD・SWAP・OVERWRITE のどれか）
        # 合成は別の流れ（スレッド）で動かすので、終わったことを画面に伝えるための受け渡し場所
        self.results = queue.Queue()

        root.title("音声トラック追加")
        root.resizable(False, False)

        frame = tk.Frame(root, padx=20, pady=16)
        frame.pack()

        # 説明
        tk.Label(
            frame,
            text=f"MP4 に、選んだ音（{AUDIO_NAMES}）を別のトラックとして入れた動画を作ります\n"
                 "ファイルは、この画面にドラッグ＆ドロップしても入れられます",
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # 1段目：MP4 を選ぶ
        tk.Button(frame, text="MP4 を選ぶ", width=12, command=self.choose_video).grid(row=1, column=0, sticky="nw")
        self.video_label = tk.Label(frame, text="まだ選んでいません", width=48, anchor="w", fg="gray")
        self.video_label.grid(row=1, column=1, sticky="w", padx=(10, 0))

        # 2段目：音声を追加 ＋ 一覧
        tk.Button(frame, text="音声を追加", width=12, command=self.choose_audio).grid(row=2, column=0, sticky="nw", pady=(8, 0))
        self.audio_list = tk.Listbox(frame, width=50, height=MAX_ADDED, activestyle="none", exportselection=False)
        self.audio_list.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(8, 0))

        # 一覧の下：並びを直すボタン
        buttons = tk.Frame(frame)
        buttons.grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(4, 0))
        tk.Button(buttons, text="上へ", width=6, command=lambda: self.move_audio(-1)).pack(side="left")
        tk.Button(buttons, text="下へ", width=6, command=lambda: self.move_audio(1)).pack(side="left", padx=(4, 0))
        tk.Button(buttons, text="外す", width=6, command=self.remove_audio).pack(side="left", padx=(4, 0))

        # 元の音の扱い方（3つから1つ選ぶ。変えると、一覧のトラック番号をすぐに書き直す）
        tk.Label(frame, text="元の音").grid(row=4, column=0, sticky="nw", pady=(8, 0))
        modes = tk.Frame(frame)
        modes.grid(row=4, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        for text, value in MODES:
            tk.Radiobutton(modes, text=text, value=value, variable=self.mode,
                           command=self.on_mode_changed).pack(anchor="w")

        # 保存先（MP4 を選ぶと表示する）
        # 保存先は長くなりやすいので、折り返して表示する（折り返す幅は、下で画面の幅に合わせる）
        self.output_label = tk.Label(frame, text="", anchor="w", justify="left", fg="gray")
        self.output_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

        # 合成するボタン（MP4 と音を1つ以上選ぶまでは押せない）
        self.merge_button = tk.Button(frame, text="合成する", width=16, state="disabled", command=self.start_merge)
        self.merge_button.grid(row=6, column=0, columnspan=2, pady=(16, 0))

        # 進み具合の棒（0〜100）。長さは下で、ボタンと一覧の幅に合わせる
        self.progress = ttk.Progressbar(frame, maximum=100, mode="determinate")
        self.progress.grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 0))

        # 結果の表示
        self.status_label = tk.Label(frame, text="", anchor="w", justify="left")
        self.status_label.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.refresh_audio_list()

        # 保存先と結果は、ボタンや一覧が並んだ部分の幅で折り返す
        # （それより広い幅で折り返すと、長い名前のときに画面が横に広がってしまう）
        root.update_idletasks()
        # 1〜4段目（ボタンと一覧と、元の音の選び方）が使っている幅（ピクセル）。文字の周りのわずかな余白の分を引いておく
        wrap = frame.grid_bbox(0, 1, 1, 4)[2] - 8
        self.output_label.config(wraplength=wrap)
        self.status_label.config(wraplength=wrap)
        self.progress.config(length=wrap)

        # 画面のどこに落としても受け取れるように、画面とその中の部品すべてを「落とし先」にする
        self.register_drop(root)

    # ---------- ドラッグ＆ドロップ ----------

    def register_drop(self, widget):
        """widget とその中の部品すべてで、ドラッグ＆ドロップを受け取れるようにする"""
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self.on_drop)
        for child in widget.winfo_children():
            self.register_drop(child)

    def on_drop(self, event):
        """ファイルが落とされたとき：拡張子を見て、MP4 の欄と音の一覧に振り分ける"""
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
        self.video_label.config(text=shorten(path.name), fg="black")
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
        selection = self.audio_list.curselection()
        return selection[0] if selection else None

    def move_audio(self, step):
        """選ばれている MP3 を、step が -1 なら1つ上へ、1 なら1つ下へ動かす"""
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
        """選ばれている MP3 を一覧から外す（ファイルそのものは消さない）"""
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
            self.audio_list.insert("end", f"トラック{track_of[index]}：{shorten(path.name)}")
        if not self.audio_paths:
            self.audio_list.insert("end", "まだ選んでいません")
            self.audio_list.itemconfig(0, fg="gray")
        elif select is not None and select >= 0:
            self.audio_list.selection_set(select)

    # ---------- 合成 ----------

    def update_button(self):
        """MP4 と音（1つ以上）がそろっていれば「合成する」を押せるようにする"""
        ready = self.video_path is not None and len(self.audio_paths) > 0
        self.merge_button.config(state="normal" if ready else "disabled")
        self.status_label.config(text="")

    def show_error(self, message):
        self.status_label.config(text=message, fg="red")

    def start_merge(self):
        """合成を始める
        合成中も画面が固まらないように、合成は別の流れ（スレッド）で動かす"""
        # 合成中に一覧が変えられても混ざらないように、今の選択を写し取っておく
        video_path = self.video_path
        audio_paths = list(self.audio_paths)
        mode = self.mode.get()
        output_path = make_output_path(video_path)
        self.merge_button.config(state="disabled")
        self.progress.config(value=0)
        self.status_label.config(text="合成しています… 0%", fg="black")

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
                self.status_label.config(text=value, fg="green")
            else:
                self.progress.config(value=0)  # 失敗したときは、棒を空に戻す
                self.status_label.config(text=value, fg="red")
            self.merge_button.config(state="normal")
            return


def main():
    root = TkinterDnD.Tk()  # ドラッグ＆ドロップを受け取れる画面
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
