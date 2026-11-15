# 音声トラック追加アプリ
# ステップ1：画面なしで、MP4 に MP3 を「2本目の音（トラック2）」として足す
# ステップ3：おかしな使い方への備え（ffmpeg がない、壊れたファイル、保存できない場所など）
# 追加    ：MP3 を最大4つまで選び、トラック2〜5に入れられるようにする
#
# できあがる MP4 の中身
#   映像         ：もとの MP4 の映像を、そのままコピー（作り直さないので、画質が落ちず速い）
#   トラック1    ：もとの MP4 に入っている音を、そのままコピー
#   トラック2〜5 ：選んだ MP3 を、選んだ順に AAC（MP4 でいちばん一般的な音の形式）に変換して入れる
#                  名前は付けない（再生ソフトが「Audio 2」「Audio 3」のように番号で表示する）
#   長さ         ：動画の長さにそろえる（MP3 が長ければ切る。短ければ、残りは無音）
#
# 使い方（確認用）
#   python add_audio.py 動画.mp4 音1.mp3 [音2.mp3 音3.mp3 音4.mp3]
#   → 動画と同じフォルダに「動画_音声追加.mp4」ができる

import subprocess
import sys
from pathlib import Path

LAST_TRACK = 5             # いちばん最後のトラックの番号（トラック5まで）
MAX_ADDED = LAST_TRACK - 1  # 足せる MP3 の数（トラック1はもとの音なので、2〜5 の4つ）
TRACK_BITRATE = "192k"     # 足すトラックの音質（1秒あたりのデータ量。大きいほど高音質）


# exe にしたアプリ（黒い画面なし）から ffmpeg を動かすと、そのたびに黒い画面が一瞬出てしまう
# Windows では CREATE_NO_WINDOW を付けて、黒い画面を出さないようにする
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def not_found_error(command):
    """ffmpeg・ffprobe そのものが見つからないときのエラー"""
    return RuntimeError(f"{command[0]} が見つかりません。ffmpeg を入れてから、もう一度試してください")


def run(command):
    """ffmpeg・ffprobe を動かして、結果を返す（日本語の名前のファイルでも大丈夫なように、文字は UTF-8 で受け取る）
    ffmpeg・ffprobe そのものが見つからないときは、理由を書いた RuntimeError を出す"""
    try:
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise not_found_error(command)


def run_with_progress(command, duration, on_progress):
    """ffmpeg を動かしながら、進み具合（0〜100 の%）を on_progress に知らせる
    ffmpeg に「-progress pipe:1」を付けると、作業中に「out_time_us=書き終わった時間（100万分の1秒）」を
    1行ずつ知らせてくれるので、それを動画の長さで割って%にする
    終わったら、ffmpeg の終わりの合図（0 なら成功）と、エラーの文章を返す"""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise not_found_error(command)

    for line in process.stdout:  # ffmpeg が1行知らせるたびに、ここが動く
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and value.isdigit():  # 最初のうちは「N/A」が来ることがあるので、数字のときだけ使う
            seconds = int(value) / 1_000_000
            on_progress(min(100.0, seconds / duration * 100))

    errors = process.stderr.read()  # 「-v error」でエラーだけにしているので、量は少ない
    return process.wait(), errors


def count_streams(path, kind):
    """ファイルの中にある流れ（ストリーム）の数を返す。kind は "v"（映像）か "a"（音）
    ファイルとして読めなかったときは None を返す"""
    result = run([
        "ffprobe", "-v", "error",
        "-select_streams", kind,           # 映像だけ、または音だけを調べる
        "-show_entries", "stream=index",   # ストリームの番号を1行ずつ出す
        "-of", "csv=p=0",
        str(path),
    ])
    if result.returncode != 0:
        return None
    return len(result.stdout.split())


def get_duration(video_path):
    """動画の長さ（秒）を返す。分からなかったときは None を返す"""
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(video_path),
    ])
    try:
        return float(result.stdout.strip())
    except ValueError:  # 数字が返ってこなかった（壊れたファイルなど）
        return None


def make_output_path(video_path):
    """保存先の名前を決める：「動画_音声追加.mp4」（もとの MP4 は書きかえない）"""
    video_path = Path(video_path)
    return video_path.with_name(video_path.stem + "_音声追加.mp4")


def check_inputs(video_path, audio_paths, output_path):
    """合成を始める前に、ファイルを調べる。問題があれば、理由を書いた RuntimeError を出す
    合成できるときは、動画の長さ（秒）を返す"""
    # MP3 の数
    if len(audio_paths) == 0:
        raise RuntimeError("MP3 を1つ以上選んでください")
    if len(audio_paths) > MAX_ADDED:
        raise RuntimeError(f"MP3 は{MAX_ADDED}つまでです（トラック{LAST_TRACK}まで）")

    # 同じ名前のファイルがあるときは止める
    # （ffmpeg の「-n」でも上書きは防げるが、そのときも「成功」の合図を返してしまうので、先に自分で調べる）
    if Path(output_path).exists():
        raise RuntimeError(f"同じ名前のファイルがすでにあります：{output_path}")

    # 選んだあとで、ファイルが動かされたり消されたりしていないか
    if not Path(video_path).is_file():
        raise RuntimeError(f"動画ファイルが見つかりません：{video_path}")
    for audio_path in audio_paths:
        if not Path(audio_path).is_file():
            raise RuntimeError(f"音のファイルが見つかりません：{audio_path}")

    # 動画として読めるか（名前だけ .mp4 のファイルや、壊れたファイルを見分ける）
    video_streams = count_streams(video_path, "v")
    duration = get_duration(video_path)
    if not video_streams or duration is None:
        raise RuntimeError("動画として読めませんでした。MP4 が壊れているか、中身が動画ではないかもしれません")

    # もとの音が、ちょうど1本あるか（トラック1にするため）
    audio_streams = count_streams(video_path, "a")
    if audio_streams == 0:
        raise RuntimeError("この動画には音が入っていないので、MP3 をトラック2からにできません")
    if audio_streams > 1:
        raise RuntimeError("この動画にはすでに音が2本以上入っているので、MP3 をトラック2からにできません")

    # MP3 が音として読めるか
    for audio_path in audio_paths:
        if not count_streams(audio_path, "a"):
            raise RuntimeError(f"音として読めませんでした。MP3 が壊れているか、中身が音ではないかもしれません：{Path(audio_path).name}")

    return duration


def add_audio_tracks(video_path, audio_paths, output_path, on_progress=None):
    """MP4 に MP3 をトラック2から順に足して、output_path に保存する
    audio_paths は MP3 の一覧（1〜4つ）。並んでいる順に、トラック2・3・4・5 になる
    on_progress を渡すと、合成中の進み具合（0〜100 の%）を知らせる
    うまくいかなかったときは、理由を書いた RuntimeError を出す"""
    audio_paths = list(audio_paths)
    duration = check_inputs(video_path, audio_paths, output_path)
    if on_progress is None:
        on_progress = lambda percent: None  # 知らせる先がなければ、何もしない

    command = ["ffmpeg", "-n"]           # -n：同じ名前のファイルがあったら、上書きせずに止める
    command += ["-v", "error", "-nostats"]  # ふだんの経過表示は出さず、エラーだけ出す
    command += ["-progress", "pipe:1"]   # 進み具合を、1行ずつ知らせてもらう
    command += ["-i", str(video_path)]   # 0番目の入力：動画
    for audio_path in audio_paths:
        command += ["-i", str(audio_path)]  # 1番目からの入力：MP3

    command += ["-map", "0:v"]           # 映像 ← 動画の映像
    command += ["-map", "0:a"]           # トラック1 ← 動画の音
    for number in range(1, len(audio_paths) + 1):
        command += ["-map", f"{number}:a:0"]  # トラック2から ← MP3 の音（入力の順番どおり）

    command += ["-c:v", "copy"]          # 映像はそのままコピー
    command += ["-c:a:0", "copy", "-disposition:a:0", "default"]  # トラック1はコピー。再生したとき最初に流れる
    for number in range(1, len(audio_paths) + 1):
        # 足したトラックは AAC に変換。最初に流れる設定はしない
        command += [f"-c:a:{number}", "aac", f"-b:a:{number}", TRACK_BITRATE, f"-disposition:a:{number}", "0"]

    command += ["-t", f"{duration:.3f}"]  # 動画の長さにそろえる
    command += [str(output_path)]

    returncode, errors = run_with_progress(command, duration, on_progress)
    if returncode != 0:
        # 作りかけのファイルが残っていたら消す
        # （始める前に「同じ名前のファイルはない」と確かめているので、ここにあるのは今回作ったものだけ）
        Path(output_path).unlink(missing_ok=True)

        if "Permission denied" in errors:
            raise RuntimeError(f"保存できませんでした。このフォルダには書き込めないようです：{Path(output_path).parent}")
        # ffmpeg のエラーは長いことがあるので、最後の数行だけ見せる
        last_lines = "\n".join(errors.strip().splitlines()[-5:])
        raise RuntimeError("合成に失敗しました\n" + last_lines)
    on_progress(100.0)  # 終わったら 100%


def main():
    if len(sys.argv) < 3:
        print("使い方：python add_audio.py 動画.mp4 音1.mp3 [音2.mp3 音3.mp3 音4.mp3]")
        return 1

    video_path = Path(sys.argv[1])
    audio_paths = [Path(p) for p in sys.argv[2:]]
    output_path = make_output_path(video_path)

    try:
        # 進み具合は、同じ行に上書きして表示する（\r は行の先頭に戻る記号）
        add_audio_tracks(video_path, audio_paths, output_path,
                         on_progress=lambda percent: print(f"\r合成しています… {percent:.0f}%", end=""))
        print()
    except RuntimeError as error:
        print()
        print(error)
        return 1

    print(f"できました：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
