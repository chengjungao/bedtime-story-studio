# -*- coding: utf-8 -*-
"""出旁白：把工程目录里的故事，用你的声音念出来。

这一层只做三件事：检查前置条件、把活派给装了 torch 的解释器、把进度念出来。
真正的推理在 `worker_tts.py` 里。
"""
import io
import json
import os
import subprocess

from . import config as cfgmod
from . import project, ui

MAX_CHUNKS_HINT = 3   # 第一次建议先跑 3 段听一下


def preflight(cfg):
    """出旁白之前要确认的东西。返回 (信息 dict, 问题列表)。"""
    problems = []
    info = {}

    paras, err = project.read_story(cfg)
    if err:
        problems.append(err)
    info["paras"] = len(paras)
    info["chars"] = project.han_count(paras)

    ref_text = project.read_ref_text(cfg)
    if not ref_text:
        problems.append(u"参考录音.txt 是空的。那段录音说了什么，一个字一个字抄进去")
    info["ref_text"] = ref_text

    ref_wav, ref_sec, rerr = project.prep_reference(cfg)
    info["ref_wav"] = ref_wav
    info["ref_sec"] = ref_sec
    if rerr:
        problems.append(rerr)
    elif ref_sec > project.REF_GOOD_SEC:
        ui.warn(u"参考录音 %.2f 秒，已经贴近 30 秒的硬上限了。超一点会直接报错"
                % ref_sec)

    # 「文字跟录音对不上」是这套流程里最难查的错：不报错，只把音色带偏。
    # 用字/秒做个粗筛 —— 正常人念中文在 2~5 字/秒之间，跑出去多半是抄错或漏抄。
    if ref_text and ref_sec > 0:
        rate = len(ref_text) / ref_sec
        info["ref_rate"] = rate
        if not (1.5 <= rate <= 5.5):
            ui.warn(u"参考文字 %d 字 ÷ 录音 %.2f 秒 = %.2f 字/秒。"
                    u"正常人念中文在 2~5 之间，这个数说明文字和录音可能对不上"
                    % (len(ref_text), ref_sec, rate))

    py = cfgmod.resolve_python(cfg)
    info["python"] = py
    if not py:
        problems.append(u"找不到装了 torch 的 Python。先跑一次安装（启动.bat 里选 0）")

    mdir = cfgmod.model_dir(cfg)
    info["model_dir"] = mdir
    miss = []
    for name, min_size in cfgmod.MODEL_FILES:
        p = os.path.join(mdir, name)
        if not os.path.isfile(p) or os.path.getsize(p) < min_size * 0.98:
            miss.append(name)
    for name, min_n in cfgmod.MODEL_SUBDIRS:
        p = os.path.join(mdir, name)
        if not os.path.isdir(p) or len(os.listdir(p)) < min_n:
            miss.append(name + u"/")
    if miss:
        problems.append(u"模型还缺 %d 个文件：%s（跑一次安装会补齐）"
                        % (len(miss), u"、".join(miss)))
    info["model_missing"] = miss
    return info, problems


def run(cfg, max_chunks=0):
    """出旁白。返回 0 表示整篇跑完。"""
    ui.title(u"第一步 / 出旁白")
    info, problems = preflight(cfg)

    ui.kv(u"工程目录", cfgmod.project_dir(cfg))
    ui.kv(u"故事", u"%d 段，%d 字" % (info["paras"], info["chars"]))
    ui.kv(u"参考录音", u"%s ｜ %.2f 秒"
          % (os.path.basename(info["ref_wav"] or u"-"), info["ref_sec"]))
    ui.kv(u"参考文字", u"%d 字" % len(info["ref_text"]))
    ui.kv(u"语速", u"%.2f" % cfg["speed"])
    if info["python"]:
        ui.kv(u"解释器", info["python"])

    if problems:
        ui.say(u"")
        for p in problems:
            ui.bad(p)
        return 2

    outdir = project.narration_dir(cfg)
    cmd = [info["python"], os.path.join(cfgmod.HERE, "worker_tts.py"),
           "--cosyvoice-dir", cfgmod.cosyvoice_dir(cfg),
           "--model", info["model_dir"],
           "--ref", info["ref_wav"],
           "--ref-text", info["ref_text"],
           "--story", project.story_path(cfg),
           "--outdir", outdir,
           "--speed", "%.4f" % cfg["speed"],
           "--fp16", "1" if cfg["fp16"] else "0"]
    if max_chunks > 0:
        cmd += ["--max-chunks", str(max_chunks)]

    ui.say(u"")
    ui.info(u"切段规则跟「整篇丢进去」完全一样，用的是官方那个分段函数。")
    if max_chunks > 0:
        ui.info(u"这次只跑前 %d 段，先听听像不像你，再决定要不要跑全篇。" % max_chunks)
    ui.say(u"")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, cwd=cfgmod.ROOT,
                         env=env, bufsize=1, universal_newlines=True,
                         encoding="utf-8", errors="replace")
    for line in p.stdout:
        line = line.rstrip(u"\r\n")
        if line.startswith(u"PROG "):
            parts = line[5:].split(u" ", 1)
            body = parts[1] if len(parts) > 1 else u""
            ui.say(u"  " + body)
        else:
            ui.say(line)
    p.wait()

    if p.returncode != 0:
        ui.say(u"")
        ui.bad(u"有段没念成（退出码 %d）。修好之后重跑，已经念好的段会跳过。"
               % p.returncode)
        return 1

    rec_path = os.path.join(outdir, u"_生成记录.json")
    if os.path.isfile(rec_path):
        rec = json.load(io.open(rec_path, encoding="utf-8"))
        sec = sum(r.get("sec", 0) for r in rec["rows"] if r.get("ok"))
        ui.say(u"")
        ui.ok(u"旁白好了：%d 段，合计 %.1f 秒" % (len(rec["segments"]), sec))
        ui.kv(u"在", os.path.join(outdir, u"全篇_拼接.wav"))
        if max_chunks > 0:
            ui.say(u"")
            ui.info(u"这次只跑了前 %d 段，没有拼全篇。听一遍 wav，"
                    u"觉得像你，就把「只跑前几段」去掉再跑一次。" % max_chunks)
    return 0


def narration_wav(cfg):
    """整篇旁白的路径（TTS 跑完之后才有）。"""
    return os.path.join(project.narration_dir(cfg), u"全篇_拼接.wav")
