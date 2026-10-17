# -*- coding: utf-8 -*-
"""一键环境：先查一遍，缺什么装什么，装完再查一遍。

为什么要这个文件
--------------
自检和安装器各干一半：自检只报告，安装器只装。用户面对两个入口，还得
自己判断该点哪个。这里把它合成一个动作：先查，环境齐了就直接说可以开工；
缺东西就说清楚缺什么、要下多少，用户按回车之后才动手，装完再查一遍给结论。

环境缺和素材缺必须分开算
----------------------
环境要下 8 GB 上下，素材只是三个文件。素材没放好却去装环境，用户白等
几十分钟，装完还是开不了工。所以两类问题在这张表里分开列：只有环境缺
才触发下载，退出码也只表示环境能不能用。

三条不动的原则
--------------
1. **不替用户装 Python 和 ffmpeg。** 这两件要动系统，装法还按系统不同，
   脚本只把准确的命令打出来，剩下的让用户自己确认。
2. **可以反复跑。** installer 的五个步骤各自会在「已经好了」时跳过，断掉的
   下半截也会接着下，所以重复跑不会重下 5 GB。
3. **不静默安装。** 缺东西时先说清楚缺什么、要下多少、磁盘够不够。

一个只有真跑过才会发现的坑
------------------------
装完必须清掉 config 里 has_torch 的缓存。装之前问过「这个解释器有 torch 吗」，
答案是没有，被缓存住了；装完再问还是「没有」，于是刚装好的环境被判成没装。
这个错不抛异常，只让结论永远错。
"""
import os
import shutil
import subprocess
import sys

from . import config as cfgmod
from . import envcheck, installer, project, ui

# 下载量与磁盘占用，都是这台机器上量过的，不是估的
GB_SOURCE = 0.05      # CosyVoice 源码，约 50 MB
GB_TORCH = 2.5        # PyTorch 2.4.0 cu121：下载 2.4 GB，取 2.5 留余量
GB_DEPS = 1.1         # 推理依赖 + openai-whisper
GB_BLANKEN = 0.92     # 模型里的 CosyVoice-BlankEN，实测 946.31 MB
GB_ON_DISK = 11.0     # 整套环境装完约占 11 GB

OK, MISS, NOTE = u"OK", u"缺", u"注意"


def _free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1073741824.0
    except Exception:
        return -1.0


def _ff_ver(ff):
    """从 ffmpeg -version 第一行里挑出像版本号的那个词。"""
    try:
        r = subprocess.run([ff, "-version"], capture_output=True, text=True,
                           timeout=60, encoding="utf-8", errors="replace")
        line = (r.stdout or u"").split(u"\n")[0]
        for word in line.split():
            if word[:1].isdigit() and u"." in word:
                return word
        return line[:40]
    except Exception:
        return u"版本读不出来"


def _torch_brief(py):
    """借 envcheck 的探针读版本与显卡。

    envcheck 那边是逐行 key/value，适合它自己打印；这里拼成一句给人看。
    探针本身要 import torch，几秒钟，全流程只跑这一次。
    """
    d = {}
    for line in envcheck._torch_info(py).strip().split(u"\n"):
        k, _, v = line.partition(u" ")
        if k in (u"TORCH", u"CUDA", u"GPU", u"VRAM"):
            d[k] = v.strip()
    return (d.get(u"TORCH", u"?"), d.get(u"CUDA", u"?"),
            d.get(u"GPU", u""), d.get(u"VRAM", u"0"))


def _model_missing_gb(miss):
    """缺的那几项要下多少 GB。按 config 里记的实测字节数算。"""
    size = 0.0
    for name, min_size in cfgmod.MODEL_FILES:
        if name in miss:
            size += min_size / 1073741824.0
    for name in miss:
        if name.endswith(u"/"):
            size += GB_BLANKEN
    return size


def audit(cfg):
    """查一遍，不装任何东西。

    返回 (env_rows, mat_rows, env_missing, mat_missing, need_gb)。
    环境行是「缺了就开不了工」的，素材行只影响这一步能不能马上跑。
    """
    env_rows, mat_rows = [], []
    env, mat = [], []
    need = 0.0

    # 启动器
    ver = u"%d.%d.%d" % tuple(sys.version_info[:3])
    if sys.version_info < (3, 8):
        env_rows.append((u"启动器 Python", MISS, ver + u"，太旧，要 3.8 以上"))
        env.append(u"Python 版本")
    elif sys.version_info[:2] >= (3, 13):
        env_rows.append((u"启动器 Python", NOTE,
                         ver + u"，装环境时会另找 3.10~3.12 建独立环境"))
    else:
        env_rows.append((u"启动器 Python", OK, ver))

    # ffmpeg
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ff and fp:
        env_rows.append((u"ffmpeg", OK, _ff_ver(ff)))
    else:
        # 这一项不替用户装，也不下载，先记在 env 里，run() 会单独处理
        env_rows.append((u"ffmpeg", MISS, u"合成和校验的必要工具，要你自己装"))
        env.append(u"ffmpeg")

    # CosyVoice 源码
    cdir = cfgmod.cosyvoice_dir(cfg)
    entry = os.path.join(cdir, "cosyvoice", "cli", "cosyvoice.py")
    if os.path.isfile(entry):
        env_rows.append((u"CosyVoice 源码", OK, cdir))
    else:
        env_rows.append((u"CosyVoice 源码", MISS, u"要拉下来，约 50 MB"))
        env.append(u"源码")
        need += GB_SOURCE

    # 装了 torch 的那个解释器
    py = cfgmod.resolve_python(cfg)
    if not py:
        env_rows.append((u"PyTorch", MISS,
                         u"下载约 2.5 GB，装完占 4.2 GB，依赖另算"))
        env.append(u"PyTorch")
        need += GB_TORCH + GB_DEPS
    else:
        tv, cuda, gpu, vram = _torch_brief(py)
        state, tail = OK, u"torch %s" % tv
        if tv.startswith(u"2.3."):
            # 2.3.1 的 Windows 轮子漏打包了整套 MKL，跑 CPU 的 svd / inv
            # 会静默打死进程，退出码 0xC06D007E。必须换 2.4.0。
            state = MISS
            tail = u"torch %s 缺 MKL，跑久了会静默死进程，要换 2.4.0" % tv
            env.append(u"PyTorch 版本")
            need += GB_TORCH
        elif cuda == u"True":
            tail += u"  CUDA 可用  %s %s GB" % (gpu, vram)
        else:
            state = NOTE
            tail += u"  没有可用 CUDA，会走 CPU，慢十倍上下"
        env_rows.append((u"PyTorch", state, tail))
        if state != MISS:
            env_rows.append((u"推理解释器", OK, py))

    # 模型
    mdir, have, miss, total = envcheck.model_status(cfg)
    if miss:
        est = _model_missing_gb(miss)
        env_rows.append((u"模型", MISS,
                         u"缺 %d 项，要下 %.2f GB" % (len(miss), est)))
        env.append(u"模型")
        need += est
    else:
        env_rows.append((u"模型", OK, u"%d 项齐，%.2f GB"
                         % (len(have), total / 1073741824.0)))

    # 素材：缺了不影响环境，只是这一步跑不了
    paras, err = project.read_story(cfg)
    if err:
        mat_rows.append((u"故事.txt", MISS, u"还没有你自己的故事"))
        mat.append(u"故事.txt")
    else:
        mat_rows.append((u"故事.txt", OK, u"%d 段，%d 字"
                         % (len(paras), project.han_count(paras))))

    ref = project.find_ref_audio(cfg)
    if ref:
        sec = project.duration(ref)
        if sec > 0:
            state = OK if sec <= project.REF_GOOD_SEC else NOTE
            mat_rows.append((u"参考录音", state, u"%.2f 秒（上限 %.1f 秒）"
                             % (sec, project.REF_MAX_SEC)))
        else:
            mat_rows.append((u"参考录音", OK, u"在，时长量不出来"))
    else:
        mat_rows.append((u"参考录音", MISS,
                         u"没放（你的声音，15~28 秒）"))
        mat.append(u"参考录音")

    rtxt = project.read_ref_text(cfg)
    if rtxt:
        mat_rows.append((u"参考录音.txt", OK, u"%d 个字符" % len(rtxt)))
    else:
        mat_rows.append((u"参考录音.txt", MISS, u"没放，或者只有占位符"))
        mat.append(u"参考录音.txt")

    mus = project.read_music(cfg)
    if mus:
        mat_rows.append((u"配乐", OK, u"%d 个" % len(mus)))
    else:
        mat_rows.append((u"配乐", NOTE, u"没给（可选，不给就只出旁白）"))

    return env_rows, mat_rows, env, mat, need


def _print(env_rows, mat_rows, cfg):
    ui.say(u"")
    ui.kv(u"项目目录", cfgmod.ROOT)
    ui.kv(u"工程目录", cfgmod.project_dir(cfg))
    ui.say(u"")
    ui.say(u"  环境")
    ui.table([u"项目", u"状态", u"说明"], env_rows, indent=4)
    ui.say(u"")
    ui.say(u"  素材")
    ui.table([u"项目", u"状态", u"说明"], mat_rows, indent=4)


def _ask(prompt):
    """读一行输入。stdin 被管道接走或者已经关了，返回 None。"""
    try:
        return input(prompt)
    except EOFError:
        return None
    except KeyboardInterrupt:
        ui.say(u"")
        return u"n"


def _need_ffmpeg(env_missing):
    """ffmpeg 是本项目唯一不替你装的东西，缺它就没必要往下走。"""
    ui.say(u"")
    ui.bad(u"缺 ffmpeg。合成和校验都要用它，本项目不替你装。")
    ui.info(u"Windows 上最快的一条（在这个窗口里跑也行）：")
    ui.info(u"    winget install Gyan.FFmpeg")
    ui.info(u"没有 winget 就到 ffmpeg.org 下压缩包，解压后把 bin 目录加进 PATH。")
    ui.info(u"装完关掉这个窗口重开，PATH 才会生效，然后再双击一次这个脚本。")
    rest = [x for x in env_missing if x != u"ffmpeg"]
    if rest:
        ui.say(u"")
        ui.info(u"另外还缺：%s。ffmpeg 装好之后再跑一次，会把它们一起处理。"
                % u"、".join(rest))
    return 1


def _done(cfg, mat_missing):
    ui.say(u"")
    ui.ok(u"环境齐了，可以开工")
    if mat_missing:
        ui.say(u"")
        ui.warn(u"素材还缺 %d 项：%s" % (len(mat_missing), u"、".join(mat_missing)))
        ui.info(u"放进这个文件夹就行，名字要对得上：")
        ui.info(u"    %s" % cfgmod.project_dir(cfg))
        ui.info(u"里面的「放这里.txt」写了放什么、参考录音怎么录。")
        ui.info(u"想先听效果就双击「启动.bat」选 5，只念前 3 段。")
    else:
        ui.say(u"")
        ui.info(u"下一步：双击「启动.bat」选 4 一条龙，")
        ui.info(u"或者在这里跑 python app.py --all")
    return 0


def run(cfg, cpu=False, mirror=True, yes=False):
    ui.title(u"一键环境")
    project.ensure(cfg)          # 工程目录和模板先备好，读素材才不会崩

    env_rows, mat_rows, env_missing, mat_missing, need = audit(cfg)
    _print(env_rows, mat_rows, cfg)

    if not env_missing:
        return _done(cfg, mat_missing)

    if u"ffmpeg" in env_missing:
        return _need_ffmpeg(env_missing)

    free = _free_gb(cfgmod.ROOT)
    ui.say(u"")
    ui.warn(u"环境还缺 %d 项：%s" % (len(env_missing), u"、".join(env_missing)))
    ui.kv(u"要下载", u"约 %.1f GB" % need)
    if free >= 0:
        ui.kv(u"磁盘可用", u"%.1f GB" % free)
        if free < need + 1.0:
            ui.bad(u"磁盘不够。先清出 %.0f GB 再说，装到一半空间不够最难收拾"
                   % (need + 1.0 - free))
            return 1
    ui.info(u"整套装完约占 %.0f GB。中途断了直接重跑这个脚本，会接着下。" % GB_ON_DISK)

    if not yes:
        ans = _ask(u"  回车开始装，输 n 先不装：")
        if ans is None:
            ui.say(u"")
            ui.info(u"没收到输入，什么都没装。")
            ui.info(u"要装就跑 python app.py --setup --yes，或者直接双击这个脚本。")
            return 1
        if ans.strip().lower() not in (u"", u"y", u"yes", u"是", u"好"):
            ui.say(u"")
            ui.info(u"没装。想装的时候再双击这个脚本就行。")
            return 1

    rc = installer.run(cfg, cpu=cpu, mirror=mirror)

    # 装之前问过「这个解释器有 torch 吗」，答案是没有，被缓存住了。
    # 不清掉的话，下面再查一遍还会说没有，刚装好的环境被判成没装。
    cfgmod.forget_torch_cache()

    ui.say(u"")
    ui.title(u"再查一遍")
    env_rows, mat_rows, env_missing, mat_missing, need = audit(cfg)
    _print(env_rows, mat_rows, cfg)

    if env_missing:
        ui.say(u"")
        ui.bad(u"还差 %d 项：%s" % (len(env_missing), u"、".join(env_missing)))
        if rc != 0:
            ui.info(u"上面找到第一处红色的报错，按它改。")
        ui.info(u"修好再跑一次这个脚本，装过的会跳过，不会重下。")
        return 1

    return _done(cfg, mat_missing)
