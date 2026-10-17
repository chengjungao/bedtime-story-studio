# -*- coding: utf-8 -*-
"""工程目录：认文件夹、收素材、把手机录音转成引擎能吃的格式。

工程目录长这样（本项目只写 旁白/ 与 成片/，其余是你的）
------------------------------------------------------
    我的故事/
        故事.txt          必填。空行分段
        参考录音.m4a      必填。你的声音，15~28 秒。wav / m4a / mp3 都认
        参考录音.txt      必填。上面那段录音的逐字文字
        配乐.mp3          可选。不给就只出旁白，不出音乐
        旁白/             本项目写
        成片/             本项目写

为什么参考录音必须配一份文字
--------------------------
零样本克隆要同时喂「音频」和「它到底说了什么」。文字对不上不会报错，
只会把音色带偏 —— 属于不报错只出错东西的那一类，所以宁可事先硬卡。
"""
import io
import os
import re
import subprocess

from . import config as cfgmod
from . import ui

AUDIO_EXT = (".wav", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".wma",
             ".amr", ".mp4", ".opus")

# 引擎里有一条硬检查：cosyvoice/cli/frontend.py 第 99 行
#   assert speech.shape[1] / 16000 <= 30
# 超过 30 秒**直接报错退出**，不是自动截断。留 0.5 秒余量卡在 29.5。
REF_MAX_SEC = 29.5
REF_MIN_SEC = 10.0
REF_GOOD_SEC = 28.0

TEMPLATE_STORY = u"""（把这段换成你的故事。空行分段，一段大约两三句，念起来才顺。）

（这是第二段。）
"""

TEMPLATE_REF = u"""（把你录的那段话，一个字一个字抄在这里。标点可以不写，字要对得上。）
"""

TEMPLATE_README = u"""这个文件夹里放四样东西，名字要一模一样：

  故事.txt        你的故事。空行分段，一段两三句。
  参考录音.m4a    你自己的声音，15~28 秒。wav / m4a / mp3 都行。
                  手机录完直接丢进来，不用转格式。
  参考录音.txt    上面那段录音的逐字文字。要一个字一个字对得上。
  配乐.mp3        可选。不给就只出旁白，不垫音乐。

录参考录音的三条：
  1. 安静房间，手机离嘴 20~30 厘米，别贴嘴。
  2. 用你哄孩子的那种口气，放慢、放软，别端着念。
  3. 别超过 28 秒。念错了接着说，磕巴和笑场都留着，那才像你。

放好之后，双击上一层的「启动.bat」，按提示走。
"""


def ensure(cfg):
    """建工程目录与模板文件。已有的文件一律不覆盖。"""
    p = cfgmod.project_dir(cfg)
    cfgmod.ensure_dir(p)
    spots = [
        (u"故事.txt", TEMPLATE_STORY),
        (u"参考录音.txt", TEMPLATE_REF),
        (u"放这里.txt", TEMPLATE_README),
    ]
    for name, body in spots:
        f = os.path.join(p, name)
        if not os.path.exists(f):
            with io.open(f, "w", encoding="utf-8") as fh:
                fh.write(body)
    return p


def story_path(cfg):
    return os.path.join(cfgmod.project_dir(cfg), u"故事.txt")


def ref_text_path(cfg):
    return os.path.join(cfgmod.project_dir(cfg), u"参考录音.txt")


def narration_dir(cfg):
    return cfgmod.ensure_dir(os.path.join(cfgmod.project_dir(cfg), u"旁白"))


def out_dir(cfg):
    return cfgmod.ensure_dir(os.path.join(cfgmod.project_dir(cfg), u"成片"))


def build_dir(cfg):
    return cfgmod.ensure_dir(os.path.join(cfgmod.project_dir(cfg), u"build"))


def find_ref_audio(cfg):
    """在工程目录里找「参考录音.*」。找到多个就取第一个并提醒。"""
    p = cfgmod.project_dir(cfg)
    if not os.path.isdir(p):
        return u""
    hits = []
    for name in sorted(os.listdir(p)):
        stem, ext = os.path.splitext(name)
        if stem == u"参考录音" and ext.lower() in AUDIO_EXT:
            hits.append(os.path.join(p, name))
    if len(hits) > 1:
        ui.warn(u"工程目录里有 %d 个「参考录音」，这次用 %s"
                % (len(hits), os.path.basename(hits[0])))
    return hits[0] if hits else u""


def _read_text(path):
    """读文本。BOM / CRLF / 全角空格都顺手处理掉。"""
    if not os.path.isfile(path):
        return u""
    with io.open(path, encoding="utf-8-sig") as f:
        t = f.read()
    t = t.replace(u"\r\n", u"\n").replace(u"\r", u"\n")
    t = t.replace(u"\u3000", u"  ")
    return t


def read_story(cfg):
    """返回 (段落列表, 问题描述)。段落＝非空行块。"""
    t = _read_text(story_path(cfg))
    if not t.strip():
        return [], u"故事.txt 是空的"
    raw = re.split(u"\n\\s*\n", t)
    paras = [re.sub(u"[ \\t]+", u" ", p).strip() for p in raw]
    paras = [p for p in paras if p and not p.startswith(u"（")]
    if not paras:
        return [], u"故事.txt 里只有占位符，还没有你自己的故事"
    han = han_count(paras)
    if han < 50:
        return [], (u"故事.txt 只有 %d 个汉字，太短了。"
                    u"至少写上十来段再说" % han)
    return paras, u""


def han_count(paras):
    """汉字数。报「多少字」一律按汉字算，不含标点 —— 标点数是虚的。"""
    return sum(len(re.findall(u"[\u4e00-\u9fff]", p)) for p in paras)


def read_ref_text(cfg):
    t = _read_text(ref_text_path(cfg))
    t = u"".join(l.strip() for l in t.split(u"\n"))
    if t.startswith(u"（"):
        return u""
    return t


def read_music(cfg):
    """配乐：工程目录下的「配乐.*」或「配乐/」目录里的全部音频。"""
    p = cfgmod.project_dir(cfg)
    hits = []
    d = os.path.join(p, u"配乐")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if os.path.splitext(name)[1].lower() in AUDIO_EXT:
                hits.append(os.path.join(d, name))
    for name in sorted(os.listdir(p)):
        stem, ext = os.path.splitext(name)
        if stem == u"配乐" and ext.lower() in AUDIO_EXT:
            hits.insert(0, os.path.join(p, name))
            break
    return hits


def prep_reference(cfg):
    """把参考录音转成 16 kHz 单声道 wav，返回 (路径, 时长秒, 错误)。

    为什么统一转 16 kHz：引擎内部按 16 kHz 取 speech token，
    前端那段 assert 也是拿 16000 当除数。手机录音多是 44.1/48 kHz 单声道，
    先转好，省得后面每次都要在推理里纠一次格式。
    """
    src = find_ref_audio(cfg)
    if not src:
        return u"", 0.0, (u"工程目录里找不到「参考录音」。放一个 "
                          u"参考录音.wav / .m4a / .mp3 进去")
    dst = os.path.join(build_dir(cfg), u"参考录音_16k.wav")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(dst):
        return u"", 0.0, (u"转了不了这个录音（%s）：%s"
                          % (os.path.basename(src), (r.stderr or u"")[-400:]))
    sec = duration(dst)
    if sec > REF_MAX_SEC:
        return dst, sec, (u"参考录音 %.2f 秒，超了。引擎硬卡 30 秒，"
                          u"超了直接报错退出。\n"
                          u"        重录一遍更短的，或者把录音断在最后一句完整的话上，"
                          u"文字也跟着改" % sec)
    if sec < REF_MIN_SEC:
        return dst, sec, (u"参考录音只有 %.2f 秒，太短了。"
                          u"引擎要从这几秒里读出音色和语气，10 秒以下学不像。"
                          u"录 15~28 秒" % sec)
    return dst, sec, u""


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of",
                        "default=nw=1:nk=1", path],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    try:
        return float((r.stdout or u"0").strip())
    except ValueError:
        return 0.0
