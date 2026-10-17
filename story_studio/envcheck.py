# -*- coding: utf-8 -*-
"""自检：只看「在不在、够不够大」，不去启动推理。只用标准库。

为什么自检要能单独跑
------------------
装环境是整个流程里最久的一步（要下 8 GB 上下）。自检把所有
「缺什么、缺多少」一次列清楚，让人在等之前就知道要等多久。
"""
import os
import shutil
import subprocess
import sys

from . import config as cfgmod
from . import project, ui


def _free_gb(path):
    try:
        u = shutil.disk_usage(path)
        return u.free / 1073741824.0
    except Exception:
        return -1.0


def _py_version(exe):
    try:
        r = subprocess.run([exe, "-c",
                            "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
                           capture_output=True, text=True, timeout=120)
        return (r.stdout or u"").strip()
    except Exception:
        return u"?"


def _torch_info(exe):
    code = (
        "import sys\n"
        "try:\n"
        "    import torch\n"
        "except Exception as e:\n"
        "    print('NO %s: %s' % (type(e).__name__, e)); sys.exit(0)\n"
        "print('TORCH', torch.__version__)\n"
        "print('CUDA', torch.cuda.is_available())\n"
        "if torch.cuda.is_available():\n"
        "    print('GPU', torch.cuda.get_device_name(0))\n"
        "    print('VRAM', '%.1f' % (torch.cuda.get_device_properties(0).total_memory / 1073741824.0))\n"
    )
    try:
        r = subprocess.run([exe, "-c", code], capture_output=True, text=True,
                           timeout=300, encoding="utf-8", errors="replace")
        return r.stdout or u""
    except Exception as e:
        return u"NO %s: %s" % (type(e).__name__, e)


def model_status(cfg):
    mdir = cfgmod.model_dir(cfg)
    have, miss, total = [], [], 0
    for name, min_size in cfgmod.MODEL_FILES:
        p = os.path.join(mdir, name)
        if os.path.isfile(p) and os.path.getsize(p) >= min_size * 0.98:
            have.append(name)
            total += os.path.getsize(p)
        else:
            miss.append(name)
    for name, min_n in cfgmod.MODEL_SUBDIRS:
        p = os.path.join(mdir, name)
        if os.path.isdir(p) and len(os.listdir(p)) >= min_n:
            have.append(name + u"/")
            for f in os.listdir(p):
                fp = os.path.join(p, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        else:
            miss.append(name + u"/")
    return mdir, have, miss, total


def run(cfg, quiet=False):
    """返回 0 表示可以开工，1 表示还缺东西。"""
    if not quiet:
        ui.title(u"自检")
    problems = []

    ui.kv(u"项目目录", cfgmod.ROOT)
    ui.kv(u"启动器 Python", u"%s（%s）"
          % (_py_version(sys.executable), sys.version.split()[0]))
    if sys.version_info < (3, 8):
        problems.append(u"启动器的 Python 太旧了，要 3.8 以上")

    free = _free_gb(cfgmod.ROOT)
    if free >= 0:
        ui.kv(u"磁盘可用", u"%.1f GB" % free)

    # ffmpeg
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if ff and fp:
        try:
            r = subprocess.run([ff, "-version"], capture_output=True,
                               text=True, timeout=60)
            ver = (r.stdout or u"").split(u"\n")[0][:60]
        except Exception:
            ver = u"版本读不出来"
        ui.kv(u"ffmpeg", u"%s" % ff)
        ui.kv(u"", ver)
    else:
        problems.append(u"找不到 ffmpeg / ffprobe。合成和校验都要用它")

    # 源码
    cdir = cfgmod.cosyvoice_dir(cfg)
    entry = os.path.join(cdir, "cosyvoice", "cli", "cosyvoice.py")
    if os.path.isfile(entry):
        ui.kv(u"CosyVoice 源码", cdir)
    else:
        problems.append(u"没有 CosyVoice 源码（%s）" % cdir)

    # 解释器
    py = cfgmod.resolve_python(cfg)
    if not py:
        problems.append(u"没有找到装了 torch 的 Python（跑一次安装）")
    else:
        ui.kv(u"推理解释器", py)
        info = _torch_info(py)
        for line in info.strip().split(u"\n"):
            if not line.strip():
                continue
            k, _, v = line.partition(u" ")
            if k == "TORCH":
                ui.kv(u"", u"torch %s" % v)
            elif k == "CUDA":
                ui.kv(u"", u"CUDA 可用 %s" % v)
                if v.strip() == u"False":
                    ui.warn(u"没有可用 CUDA，会用 CPU 跑，慢十倍上下")
            elif k == "GPU":
                ui.kv(u"", u"显卡 %s" % v)
            elif k == "VRAM":
                ui.kv(u"", u"显存 %s GB" % v)
            elif k.startswith("NO"):
                pass

    # 模型
    mdir, have, miss, total = model_status(cfg)
    if miss:
        problems.append(u"模型缺 %d 项（%s）" % (len(miss), u"、".join(miss)))
        ui.kv(u"模型目录", u"%s（缺 %d 项）" % (mdir, len(miss)))
    else:
        ui.kv(u"模型目录", u"%s（%d 项齐，%.2f GB）"
              % (mdir, len(have), total / 1073741824.0))

    # 素材
    pdir = cfgmod.project_dir(cfg)
    ui.say(u"")
    ui.kv(u"工程目录", pdir)
    paras, err = project.read_story(cfg)
    if err:
        problems.append(err)
    else:
        han = project.han_count(paras)
        ui.kv(u"", u"故事 %d 段，%d 字" % (len(paras), han))
    ref = project.find_ref_audio(cfg)
    if ref:
        ui.kv(u"", u"参考录音 %s" % os.path.basename(ref))
    else:
        problems.append(u"工程目录里没有「参考录音」")
    rtxt = project.read_ref_text(cfg)
    if rtxt:
        ui.kv(u"", u"参考文字 %d 字" % len(rtxt))
    else:
        problems.append(u"工程目录里没有「参考录音.txt」或它是空的")
    mus = project.read_music(cfg)
    ui.kv(u"", u"配乐 %d 个%s" % (len(mus), u"" if mus else u"（可选，不给就只出旁白）"))

    ui.say(u"")
    if problems:
        ui.rule(u"-")
        for p in problems:
            ui.bad(p)
        ui.rule(u"-")
        if not quiet:
            ui.say(u"")
            ui.info(u"要装环境就走一遍安装；只是素材没放好，直接在工程目录里补齐。")
        return 1
    ui.ok(u"都齐了，可以开工")
    return 0
