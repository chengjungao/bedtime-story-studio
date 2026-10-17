# -*- coding: utf-8 -*-
"""装环境：拉源码、建独立环境、装 PyTorch、装依赖、下模型。

四件容易踩的事，都写进了代码里
----------------------------
1. **不要用上游 requirements.txt 里的 torch 版本。**
   上游锁 `torch==2.3.1`，而 2.3.1 的 Windows 轮子漏打包了整套 MKL：
   import 能过、CUDA 能过，可一旦跑 CPU 的 svd / inv 就**静默打死整个进程**
   （退出码 0xC06D007E），而且同一个文件跑两次还可能不同结果。
   所以本项目锁 **2.4.0**，它的 torch_cpu.dll 导入表里一个 mkl 都没有。
2. **不能装 tensorboard。** 它要求 protobuf < 4.24，而 CosyVoice 依赖 4.25，
   两者互斥，pip 会直接 ResolutionImpossible。tensorboard 只被训练脚本用，
   推理路径根本不进。
3. **要装 openai-whisper。** `cosyvoice/cli/frontend.py` 第一行就 import 它，
   缺了连模型都加载不了。它是源码包，要加 `--no-build-isolation` 才装得干净。
4. **模型不要全量拉。** 仓库里三份各约 1 GB 的权重推理根本不加载
   （llm.rl.pt / speech_tokenizer_v3.batch.onnx / flow.decoder.estimator.fp32.onnx），
   全量 9.08 GB，只拉必需的是 5.05 GB。
"""
import io
import os
import shutil
import subprocess
import sys

from . import config as cfgmod
from . import envcheck, ui

REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"
REPO_ZIP = "https://codeload.github.com/FunAudioLLM/CosyVoice/zip/refs/heads/main"
MODEL_REPO = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
MODEL_SKIP = ["llm.rl.pt", "speech_tokenizer_v3.batch.onnx",
              "flow.decoder.estimator.fp32.onnx", "*.incomplete",
              "vllm/*", "asset/*"]
TORCH_VER = "2.4.0"
TORCH_INDEX = "https://download.pytorch.org/whl/cu121"
TORCH_INDEX_CPU = "https://download.pytorch.org/whl/cpu"
PIP_MIRROR = "https://mirrors.aliyun.com/pypi/simple/"
HF_ENDPOINT = "https://hf-mirror.com"


def _sh(cmd, cwd=None, env=None, tail=0):
    """跑一条命令并把输出实时打出来。返回退出码。"""
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONUTF8"] = "1"
    if env:
        e.update(env)
    p = subprocess.Popen(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    lines = []
    for line in p.stdout:
        line = line.rstrip(u"\r\n")
        lines.append(line)
        if tail and len(lines) > tail:
            lines = lines[-tail:]
            continue
        ui.say(u"    " + line)
    p.wait()
    if tail and p.returncode != 0:
        for line in lines:
            ui.say(u"    " + line)
    return p.returncode


def _which_git():
    return shutil.which("git")


def _venv_base():
    """找一个能建 venv 的 Python 解释器。

    PyTorch 2.4.0 只给 cp38~cp312 出了轮子，所以 3.13 建出来的环境
    会卡在「装不上 torch」。启动器自己是 3.13 的话，这里去找
    py 启动器上的 3.10 / 3.11 / 3.12。
    """
    if (3, 10) <= sys.version_info[:2] <= (3, 12):
        return sys.executable
    for v in ("3.12", "3.11", "3.10"):
        r = subprocess.run(["py", "-%s" % v, "-c",
                            "import sys;print(sys.executable)"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        exe = (r.stdout or u"").strip()
        if r.returncode == 0 and exe and os.path.isfile(exe):
            ui.info(u"启动器是 %d.%d，改用 Python %s 建环境"
                    % (sys.version_info[0], sys.version_info[1], v))
            return exe
    return u""


def step_source(cfg):
    cdir = cfgmod.cosyvoice_dir(cfg)
    entry = os.path.join(cdir, "cosyvoice", "cli", "cosyvoice.py")
    if os.path.isfile(entry):
        ui.ok(u"源码已就位：%s" % cdir)
        return True
    parent = os.path.dirname(cdir)
    cfgmod.ensure_dir(parent)
    git = _which_git()
    if git:
        ui.info(u"从 GitHub 拉源码（约 50 MB）")
        rc = _sh([git, "clone", "--depth", "1", REPO_URL, cdir], tail=6)
        if rc == 0:
            ui.ok(u"源码到位")
            return True
        ui.warn(u"git clone 失败，改用下载 zip")
    ui.info(u"下载源码压缩包")
    tmp = os.path.join(parent, "_cosyvoice_src.zip")
    rc = _sh([sys.executable, "-c",
              "import urllib.request,sys;"
              "urllib.request.urlretrieve(sys.argv[1], sys.argv[2])",
              REPO_ZIP, tmp], tail=3)
    if rc != 0:
        ui.bad(u"源码下不下来。检查一下网络，或者手动 clone 到 %s" % cdir)
        return False
    import zipfile
    with zipfile.ZipFile(tmp) as z:
        z.extractall(parent)
    got = os.path.join(parent, "CosyVoice-main")
    if os.path.isdir(got):
        if os.path.isdir(cdir):
            shutil.rmtree(cdir)
        os.rename(got, cdir)
    try:
        os.remove(tmp)
    except OSError:
        pass
    ui.ok(u"源码到位")
    return True


def step_venv(cfg):
    vpy = cfgmod.venv_python()
    if os.path.isfile(vpy):
        ui.ok(u"独立环境已有：%s" % os.path.dirname(os.path.dirname(vpy)))
        return vpy
    base = _venv_base()
    if not base:
        ui.bad(u"需要一个 Python 3.10 / 3.11 / 3.12 来建环境。"
               u"当前启动器是 %d.%d" % sys.version_info[:2])
        ui.info(u"到 python.org 装一个 3.11，装完再跑一次这个窗口。")
        return u""
    ui.info(u"建独立环境（不污染你机器上的 Python）")
    rc = _sh([base, "-m", "venv",
              os.path.join(cfgmod.ROOT, cfgmod.VENV_DIRNAME)], tail=4)
    if rc != 0 or not os.path.isfile(vpy):
        ui.bad(u"建环境失败。看上面最后一行的报错")
        return u""
    _sh([vpy, "-m", "pip", "install", "--upgrade", "pip", "-q",
         "-i", PIP_MIRROR], tail=2)
    ui.ok(u"环境建好：%s" % vpy)
    return vpy


def step_torch(cfg, vpy, cpu=False):
    probe = [vpy, "-c", "import torch;print(torch.__version__)"]
    r = subprocess.run(probe, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0 and TORCH_VER in (r.stdout or u""):
        ui.ok(u"PyTorch 已装：%s" % (r.stdout or u"").strip())
        return True
    idx = TORCH_INDEX_CPU if cpu else TORCH_INDEX
    ui.info(u"装 PyTorch %s（%s），下载约 2.5 GB，慢慢等"
            % (TORCH_VER, u"CPU 版" if cpu else u"CUDA 12.1 版"))
    rc = _sh([vpy, "-m", "pip", "install", "--no-cache-dir",
              "torch==%s" % TORCH_VER, "torchaudio==%s" % TORCH_VER,
              "--index-url", idx], tail=8)
    if rc != 0:
        ui.bad(u"PyTorch 没装上。")
        ui.info(u"国内可以换镜像再试：")
        ui.info(u"  %s -m pip install torch==%s torchaudio==%s "
                u"--index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu121"
                % (vpy, TORCH_VER, TORCH_VER))
        return False
    ui.ok(u"PyTorch 装好")
    return True


def step_deps(cfg, vpy):
    req = os.path.join(cfgmod.ROOT, "requirements.txt")
    if not os.path.isfile(req):
        ui.bad(u"缺 requirements.txt")
        return False
    ui.info(u"装推理依赖（约 1.2 GB）")
    rc = _sh([vpy, "-m", "pip", "install", "--no-cache-dir", "-r", req,
              "-i", PIP_MIRROR, "--trusted-host", "mirrors.aliyun.com"],
             tail=8)
    if rc != 0:
        ui.warn(u"依赖有一次没装完，重试一次")
        rc = _sh([vpy, "-m", "pip", "install", "--no-cache-dir", "-r", req,
                  "-i", PIP_MIRROR, "--trusted-host", "mirrors.aliyun.com"],
                 tail=8)
    if rc != 0:
        ui.bad(u"依赖没装完，看上面最后几行")
        return False
    # whisper 是源码包，单独用 --no-build-isolation 装才稳
    ui.info(u"装 openai-whisper（前端要 import 它）")
    rc = _sh([vpy, "-m", "pip", "install", "--no-cache-dir",
              "--no-build-isolation", "openai-whisper==20231117",
              "-i", PIP_MIRROR], tail=6)
    if rc != 0:
        ui.bad(u"openai-whisper 装不上。缺了它连模型都加载不了")
        return False
    ui.ok(u"依赖齐了")
    return True


def step_model(cfg, vpy, mirror=True):
    mdir, have, miss, total = envcheck.model_status(cfg)
    if not miss:
        ui.ok(u"模型已齐：%.2f GB" % (total / 1073741824.0))
        return True
    cfgmod.ensure_dir(mdir)
    env = {"HF_ENDPOINT": HF_ENDPOINT} if mirror else {}
    code = (
        "import sys\n"
        "from huggingface_hub import snapshot_download\n"
        "snapshot_download(%r, local_dir=%r, max_workers=2,"
        " ignore_patterns=%r, resume_download=True)\n"
        "print('DONE')\n" % (MODEL_REPO, mdir, MODEL_SKIP)
    )
    ui.info(u"下模型（必需部分 5.05 GB，只拉推理要用的）")
    rc = _sh([vpy, "-c", code], env=env, tail=10)
    if rc != 0 and mirror:
        ui.warn(u"走镜像没下完，去掉镜像再试一次")
        rc = _sh([vpy, "-c", code], tail=10)
    # 清掉没下完的碎片，否则它们会一直占着空间，也会让体积账算不清
    for name in os.listdir(mdir) if os.path.isdir(mdir) else []:
        if name.endswith(".incomplete"):
            try:
                os.remove(os.path.join(mdir, name))
            except OSError:
                pass
    mdir, have, miss, total = envcheck.model_status(cfg)
    if miss:
        ui.bad(u"还缺 %d 项：%s" % (len(miss), u"、".join(miss)))
        ui.info(u"再跑一次安装会断点续传，不用从头下")
        return False
    ui.ok(u"模型齐了：%.2f GB" % (total / 1073741824.0))
    return True


def run(cfg, cpu=False, mirror=True):
    ui.title(u"装环境")
    ui.info(u"这一步要下 8 GB 上下，视网速几十分钟。中途断了可以重跑，会接着下。")

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        ui.bad(u"没装 ffmpeg。它是合成和校验的必要工具，本项目不替你装。")
        ui.info(u"Windows 上最快的一条：")
        ui.info(u"    winget install Gyan.FFmpeg")
        ui.info(u"装完**关掉这个窗口重开**，PATH 才会生效。")
        return 2

    ui.step(1, 5, u"拉 CosyVoice 源码")
    if not step_source(cfg):
        return 1

    ui.step(2, 5, u"建独立环境")
    vpy = step_venv(cfg)
    if not vpy:
        return 1

    ui.step(3, 5, u"装 PyTorch")
    if not step_torch(cfg, vpy, cpu=cpu):
        return 1

    ui.step(4, 5, u"装推理依赖")
    if not step_deps(cfg, vpy):
        return 1

    ui.step(5, 5, u"下模型")
    if not step_model(cfg, vpy, mirror=mirror):
        return 1

    # 这三项换台机器就全变，写进 config.local.json（不进仓库）
    cfgmod.save_local({"python": vpy,
                       "cosyvoice_dir": cfgmod.cosyvoice_dir(cfg),
                       "model_dir": cfgmod.model_dir(cfg)})
    cfg["python"] = vpy

    ui.say(u"")
    ui.ok(u"装完了")
    return 0


def write_default_requirements(path):
    """万一 requirements.txt 丢了，能补一份回来。"""
    body = u"""# 本项目的依赖清单（不是上游那份原样）
#
# 与上游 requirements.txt 的三处差别，每一处都有原因：
#   1. 没有 torch / torchaudio —— 由安装器单独锁 2.4.0（上游锁的是 2.3.1，
#      那个版本的 Windows 轮子缺 MKL，跑 CPU 的 svd / inv 会静默打死进程）
#   2. 没有 tensorboard —— 它要 protobuf<4.24，与本清单的 4.25 互斥
#   3. 没有 openai-whisper —— 它是源码包，安装器单独用 --no-build-isolation 装
conformer==0.3.2
deepspeed==0.15.1; sys_platform == 'linux'
diffusers==0.29.0
huggingface_hub
hydra-core==1.3.2
HyperPyYAML==1.2.3
inflect==7.3.1
librosa==0.10.2
modelscope==1.20.0
networkx
numpy==1.26.4
omegaconf==2.3.0
onnx==1.16.0
onnxruntime==1.18.0
protobuf==4.25
pyworld==0.3.4
rich==13.7.1
soundfile==0.12.1
transformers==4.51.3
x-transformers==2.11.24
wetext==0.0.4
wget==3.2
"""
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
