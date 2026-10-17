# -*- coding: utf-8 -*-
"""路径、常量、配置读写。只用标准库。

设计上的两条底线
----------------
1. **本包只依赖标准库**。TTS 那一环要 torch，而 torch 要单独装；
   把「要装东西」的部分关在 `worker_tts.py` 一个文件里，
   这样其余步骤在任何 Python 3.8+ 上都能跑。
2. **所有可调项都写在 config.json**，第一次运行自动生成。
   代码里不留「只对作者机器成立」的绝对路径。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CONFIG_PATH = os.path.join(ROOT, "config.json")
# 「只对这台机器成立」的东西（解释器在哪、CosyVoice 装哪了）写到这个文件。
# config.json 进仓库，这一份不进 —— 否则仓库里全是别人机器上的绝对路径。
LOCAL_CONFIG_PATH = os.path.join(ROOT, "config.local.json")

DEFAULT_PROJECT_NAME = u"我的故事"
COSYVOICE_DIRNAME = u"CosyVoice"
VENV_DIRNAME = u".venv"

# 模型推理**必需**的文件与它们的大小下限（字节）。
# 上游仓库里还有 llm.rl.pt / speech_tokenizer_v3.batch.onnx /
# flow.decoder.estimator.fp32.onnx 三份各约 1 GB 的权重，推理路径完全不加载，
# 所以安装器不拉它们（一共省下约 4.1 GB）。
# 尺寸取实测值的 98%，留出版本差异的余量；判断依据是「在不在、够不够大」，
# 而不是精确字节数 —— 精确字节数换个模型版本就全错。
MODEL_FILES = [
    (u"llm.pt", 2024669519),
    (u"flow.pt", 1329116148),
    (u"hift.pt", 83202622),
    (u"speech_tokenizer_v3.onnx", 969451503),
    (u"campplus.onnx", 28303423),
    (u"cosyvoice3.yaml", 6934),
]
MODEL_SUBDIRS = [(u"CosyVoice-BlankEN", 5)]

DEFAULTS = {
    # 工程目录。空 = 项目根下的「我的故事」
    "project": "",
    # 跑 TTS 的解释器。空 = 自动探测（见 resolve_python）
    "python": "",
    # CosyVoice 源码目录。空 = 项目根下的 CosyVoice
    "cosyvoice_dir": "",
    # 模型目录。空 = cosyvoice_dir/pretrained_models/Fun-CosyVoice3-0.5B
    "model_dir": "",

    # 语速。0.85 是这篇的定版：合成 3.21 字/秒，作者本人 3.09 字/秒。
    # 1.0 出来是 3.77 字/秒，比真人快 22%，念睡前故事偏赶。
    "speed": 0.85,
    "fp16": True,

    # 成片结构（秒）
    "lead": 2.0,
    "tail": 6.0,
    # 电平：旁白归一到这个均值，音乐垫再比它低 bed_below_db
    "narration_db": -22.0,
    "bed_below_db": 24.0,
    "fade_in": 0.30,
    "fade_out": 5.0,
    "limiter": 0.97,
    "sample_rate": 44100,
}


def _is_windows():
    return os.name == "nt"


def _read(path):
    """读一份 json，读不动就当空的。配置坏了不该让整个程序起不来。"""
    try:
        with io.open(path, encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except Exception as e:
        sys.stderr.write(u"%s 读不动（%s），这次忽略\n" % (os.path.basename(path), e))
        return {}


def load():
    """读配置：config.json 打底，config.local.json 覆盖。

    两份分开是有意的。config.json 是模板，进仓库；本机的解释器路径、
    CosyVoice 装在哪，这些换台机器就全变，写进 config.local.json，
    那一份不进仓库。
    """
    cfg = dict(DEFAULTS)
    if os.path.isfile(CONFIG_PATH):
        cfg.update(_read(CONFIG_PATH))
    else:
        save(cfg)            # 首次运行：照默认值生成一份模板
    cfg.update(_read(LOCAL_CONFIG_PATH))
    return cfg


def save(cfg):
    with io.open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write(u"\n")


def save_local(d):
    """把本机相关的几个键写进 config.local.json，不动 config.json。"""
    cur = _read(LOCAL_CONFIG_PATH)
    cur.update(d)
    with io.open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
        f.write(u"\n")


def project_dir(cfg):
    """工程目录的绝对路径。"""
    p = (cfg.get("project") or u"").strip()
    if not p:
        return os.path.join(ROOT, DEFAULT_PROJECT_NAME)
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    return os.path.abspath(p)


def cosyvoice_dir(cfg):
    p = (cfg.get("cosyvoice_dir") or u"").strip()
    if not p:
        return os.path.join(ROOT, COSYVOICE_DIRNAME)
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    return os.path.abspath(p)


def model_dir(cfg):
    p = (cfg.get("model_dir") or u"").strip()
    if p:
        if not os.path.isabs(p):
            p = os.path.join(ROOT, p)
        return os.path.abspath(p)
    return os.path.join(cosyvoice_dir(cfg), "pretrained_models",
                        u"Fun-CosyVoice3-0.5B")


def venv_python():
    """安装器建的独立环境里的解释器路径（不一定存在）。"""
    if _is_windows():
        return os.path.join(ROOT, VENV_DIRNAME, "Scripts", "python.exe")
    return os.path.join(ROOT, VENV_DIRNAME, "bin", "python")


def resolve_python(cfg):
    """找出「能 import torch」的那个解释器。

    顺序：config.json 指定的 → 项目目录下的 .venv → 当前解释器自己。
    找不到返回空串，调用方据此提示去装环境。
    """
    cands = []
    p = (cfg.get("python") or u"").strip().strip('"')
    if p:
        cands.append(p if os.path.isabs(p) else os.path.join(ROOT, p))
    cands.append(venv_python())
    cands.append(sys.executable)
    seen = set()
    for c in cands:
        c = os.path.abspath(c)
        if c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        if has_torch(c):
            return c
    return u""


_TORCH_CACHE = {}


def has_torch(exe):
    """问那个解释器「你装没装 torch」。带缓存，同一进程只问一次。"""
    if exe in _TORCH_CACHE:
        return _TORCH_CACHE[exe]
    import subprocess
    try:
        r = subprocess.run([exe, "-c", "import torch, torchaudio"],
                           capture_output=True, timeout=180)
        ok = r.returncode == 0
    except Exception:
        ok = False
    _TORCH_CACHE[exe] = ok
    return ok


def ensure_dir(p):
    if p and not os.path.isdir(p):
        os.makedirs(p)
    return p
