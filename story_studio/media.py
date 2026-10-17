# -*- coding: utf-8 -*-
"""ffmpeg / ffprobe 封装，加上纯标准库的 wav 测量。只用标准库。

两个踩过的坑写在函数里：volumedetect 的日志级别、mean_volume 不是 RMS。
"""
import array
import os
import re
import subprocess
import sys
from operator import mul

MEAN_RE = re.compile(r"mean_volume:\s*(-?[\d.]+) dB")
MAX_RE = re.compile(r"max_volume:\s*(-?[\d.]+) dB")


def run(cmd, quiet=True):
    """跑一条命令，失败就把 stderr 尾部打出来。返回 CompletedProcess。"""
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 and not quiet:
        print((r.stderr or u"")[-2500:])
    return r


def need(cmd):
    """失败就抛，带完整 stderr。"""
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(u"命令失败（rc=%d）：%s\n%s"
                           % (r.returncode, cmd[0], (r.stderr or u"")[-2000:]))
    return r


def have(tool):
    from shutil import which
    return which(tool) is not None


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    try:
        return float((r.stdout or u"0").strip())
    except ValueError:
        return 0.0


def stream_info(path):
    """返回第一个音频流的采样率/声道/编码。"""
    import json
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=sample_rate,channels,codec_name,bits_per_sample",
             "-of", "json", path])
    try:
        d = json.loads(r.stdout or u"{}")
    except ValueError:
        return {}
    streams = d.get("streams") or [{}]
    return streams[0]


def mean_db(path, ss=None, t=None):
    """用 volumedetect 量均值电平（dBFS）。

    两个坑：
    · 不能加 `-v error` —— volumedetect 的结论打在 info 级日志上，
      加了 -v error 就什么都读不到，会误判成「这个文件没声音」。
    · `mean_volume` 不是 RMS，它是 20·log10(mean(|x|))。
      做相对比较够用，但别当 RMS 记账。
    """
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if ss is not None:
        cmd += ["-ss", "%.3f" % ss]
    if t is not None:
        cmd += ["-t", "%.3f" % t]
    cmd += ["-i", path, "-af", "volumedetect", "-f", "null", "-"]
    r = run(cmd)
    m = MEAN_RE.search(r.stderr or u"")
    if not m:
        raise RuntimeError(u"量不到 %s 的电平" % os.path.basename(path))
    return float(m.group(1))


def read_pcm(path, ar=None, ac=None):
    """把任意音频解成 16 位整数样本，返回 (array('h'), 声道数, 采样率)。

    为什么让 ffmpeg 解码而不是用标准库的 wave：
    torchaudio 存出来的 wav 用的是 WAVE_FORMAT_EXTENSIBLE，标准库 `wave`
    读它会直接抛 unknown format —— 而那个文件是上游写的，改不了。
    走 ffmpeg 解成裸 s16le，容器和编码的差异全部消失，wav / mp3 / m4a 都能读。

    为什么不用 numpy / soundfile：这一步要在「什么都没装」的机器上也能跑，
    而 ffmpeg 反正已经是合成与校验的硬依赖。
    """
    if ar is None or ac is None:
        st = stream_info(path)
        if ar is None:
            ar = int(st.get("sample_rate") or 44100)
        if ac is None:
            ac = int(st.get("channels") or 1)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
           "-f", "s16le", "-acodec", "pcm_s16le",
           "-ar", str(ar), "-ac", str(ac), "-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    raw = r.stdout or b""
    if len(raw) % 2:
        raw = raw[:-1]
    a = array.array("h")
    a.frombytes(raw)
    if sys.byteorder == "big":
        a.byteswap()
    return a, ac, ar


def block_db(a, nch, sr, block_sec):
    """按 block_sec 切块算 RMS（dBFS，满刻度 32768 对应 0 dB），返回列表。

    ⚠️ 必须除以 32768 再取对数。忘了这一步，整数样本的平方均值在 1e9 量级，
    算出来是 +40 多 dB 的正数，看上去「有声音」，实际上判据全错。
    这个错不报异常，只会让所有电平判据失灵。

    `sum(map(mul, blk, blk))` 是 C 速度的；换成 for 循环会慢十倍以上，
    500 秒的成片有 2200 万个样本，差的就是几秒和几十秒。
    """
    from math import log10
    per = max(1, int(round(block_sec * sr)))
    step = per * nch
    n = len(a)
    out = []
    full = 32768.0 * 32768.0
    for i in range(0, n - step + 1, step):
        blk = a[i:i + step]
        ms = sum(map(mul, blk, blk)) / float(len(blk))
        out.append(10.0 * log10(max(ms / full, 1e-12)))
    return out


def db(x):
    from math import log10
    return 20.0 * log10(max(float(x), 1e-12))


def peak_of(a):
    """峰值（0~1）与削顶样本数。整数 PCM 的满刻度是 32767。"""
    if not a:
        return 0.0, 0
    pk = max(max(a), -min(a)) / 32768.0
    if pk < 0.999:
        return pk, 0
    thr = int(0.999 * 32767)
    return pk, sum(1 for v in a if v >= thr or v <= -thr)


def find_gaps(db_seq, block_sec, thr_db):
    """把连续低于 thr_db 的块合并成 (起点秒, 长度秒)。"""
    out = []
    i = 0
    n = len(db_seq)
    while i < n:
        if db_seq[i] < thr_db:
            j = i
            while j < n and db_seq[j] < thr_db:
                j += 1
            out.append((i * block_sec, (j - i) * block_sec))
            i = j
        else:
            i += 1
    return out


def trend(db_seq, block_sec):
    """最小二乘斜率（dB/秒）+ 首末值。

    ⚠️ 判淡入淡出**不能拿两格相减**：音乐在淡出里还有重音，单格对单格
       会得出「后一格更响」的假结论（踩过一次，白改了两版判据）。
    """
    n = len(db_seq)
    if n < 2:
        return 0.0
    xs = [i * block_sec for i in range(n)]
    mx = sum(xs) / float(n)
    my = sum(db_seq) / float(n)
    num = sum((xs[i] - mx) * (db_seq[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    return num / den if den else 0.0
