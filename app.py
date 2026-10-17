# -*- coding: utf-8 -*-
"""用你的声音读睡前故事 —— 入口。

直接双击「启动.bat」最省事；想写脚本就带参数：
    python app.py --setup              一键：先查，缺什么装什么，装完再查
    python app.py --check              只看缺什么，不装东西
    python app.py --install            装环境
    python app.py --tts                出旁白
    python app.py --trial              只跑前 3 段，先听听像不像你
    python app.py --mix                合成成片
    python app.py --verify             出厂校验
    python app.py --all                一条龙
    python app.py --example            把示例工程拷进「我的故事」
    python app.py --project 别的目录   换工程目录
    python app.py --install --cpu      没 N 卡时装 CPU 版 PyTorch
    python app.py --setup --yes        一键装，中途不问
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from story_studio import (config as cfgmod, envcheck, installer, mix,
                          project, setup, tts, ui, verify)

BANNER = u"""
  用你的声音读睡前故事
  故事是自己写的，声音是自己录的，成品是一段能直接放给孩子听的音频
"""


def _menu(cfg):
    ui.say(BANNER)
    ui.kv(u"工程目录", cfgmod.project_dir(cfg))
    ui.kv(u"项目目录", cfgmod.ROOT)
    ui.say(u"")
    ui.say(u"   0  一键环境（先查，缺什么装什么；第一次要下 8 GB 上下）")
    ui.say(u"   1  出旁白（用你的声音念整篇）")
    ui.say(u"   2  合成成片（垫音乐、加引子和收尾）")
    ui.say(u"   3  出厂校验（一条一条量过去）")
    ui.say(u"   4  一条龙：1 → 2 → 3")
    ui.say(u"   5  只跑前 3 段，先听听像不像你")
    ui.say(u"   6  自检（不装东西，只看缺什么）")
    ui.say(u"   7  换工程目录")
    ui.say(u"   q  退出")
    ui.say(u"")


def _ask(prompt, default=u""):
    try:
        s = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return u"q"
    return s or default


def _change_project(cfg):
    ui.say(u"")
    ui.info(u"把文件夹拖进这个窗口再回车就行，也可以直接粘贴路径。")
    ui.info(u"留空表示用默认的「我的故事」。")
    p = _ask(u"  工程目录：")
    if p == u"q":
        return
    p = p.strip().strip('"').strip(u"'")
    cfg["project"] = p
    # 工程目录是这台机器上的路径，写进 config.local.json
    cfgmod.save_local({"project": p})
    project.ensure(cfg)
    ui.ok(u"工程目录改成：%s" % cfgmod.project_dir(cfg))


def _example(cfg):
    src = os.path.join(cfgmod.ROOT, "examples", u"睡前故事_小熊与月亮")
    if not os.path.isdir(src):
        ui.bad(u"示例工程不见了：%s" % src)
        return 1
    dst = cfgmod.project_dir(cfg)
    cfgmod.ensure_dir(dst)
    n = 0
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isfile(s) and not os.path.exists(d):
            shutil.copy2(s, d)
            n += 1
    ui.ok(u"示例放进去了 %d 个文件 -> %s" % (n, dst))
    ui.info(u"里面有一份 1285 字的故事、配套的参考文本和说明。参考录音得你自己录。")
    return 0


def interactive(cfg):
    project.ensure(cfg)
    while True:
        ui.say(u"")
        _menu(cfg)
        c = _ask(u"  选一个：").lower()
        if c in (u"q", u"quit", u"exit"):
            return 0
        if c == u"0":
            # 走一键：先查再装，装完再查。比直接调安装器只多一件小事，
            # 但很重要：环境已经齐的人按 0 只会看到一份清单，
            # 不会被莫名其妙地问「要不要下 8 GB」。
            rc = setup.run(cfg)
        elif c == u"1":
            rc = tts.run(cfg)
        elif c == u"2":
            rc = mix.run(cfg)
        elif c == u"3":
            rc = verify.run(cfg)
        elif c == u"4":
            rc = run_all(cfg)
        elif c == u"5":
            rc = tts.run(cfg, max_chunks=3)
        elif c == u"6":
            rc = envcheck.run(cfg)
        elif c == u"7":
            _change_project(cfg)
            rc = 0
        else:
            ui.warn(u"没有这个选项")
            rc = 0
        if rc not in (0, None):
            ui.say(u"")
            ui.info(u"这一步没走完（退出码 %s）。修好之后可以只重跑这一步。" % rc)


def run_all(cfg):
    project.ensure(cfg)
    rc = tts.run(cfg)
    if rc != 0:
        ui.say(u"")
        ui.bad(u"旁白没出完，后面的步骤先不跑。")
        return rc
    rc = mix.run(cfg)
    if rc != 0:
        return rc
    return verify.run(cfg)


def main():
    ui.setup()
    ap = argparse.ArgumentParser(add_help=True, description=u"用你的声音读睡前故事")
    ap.add_argument("--check", action="store_true", help=u"只自检")
    ap.add_argument("--setup", action="store_true", help=u"一键：先查，缺什么装什么")
    ap.add_argument("--yes", action="store_true", help=u"一键装时不问，直接开始")
    ap.add_argument("--install", action="store_true", help=u"装环境")
    ap.add_argument("--tts", action="store_true", help=u"出旁白")
    ap.add_argument("--trial", action="store_true", help=u"只跑前 3 段")
    ap.add_argument("--mix", action="store_true", help=u"合成成片")
    ap.add_argument("--verify", action="store_true", help=u"出厂校验")
    ap.add_argument("--all", action="store_true", help=u"一条龙")
    ap.add_argument("--example", action="store_true", help=u"放入示例工程")
    ap.add_argument("--project", default=u"", help=u"指定工程目录")
    ap.add_argument("--cpu", action="store_true", help=u"装 CPU 版 PyTorch")
    ap.add_argument("--no-mirror", action="store_true", help=u"下模型不走镜像")
    a = ap.parse_args()

    cfg = cfgmod.load()
    if a.project:
        cfg["project"] = a.project
        cfgmod.save_local({"project": a.project})

    if a.check:
        rc = envcheck.run(cfg)
    elif a.setup:
        rc = setup.run(cfg, cpu=a.cpu, mirror=not a.no_mirror, yes=a.yes)
    elif a.install:
        rc = installer.run(cfg, cpu=a.cpu, mirror=not a.no_mirror)
        if rc == 0:
            envcheck.run(cfg)
    elif a.example:
        project.ensure(cfg)
        rc = _example(cfg)
    elif a.trial:
        rc = tts.run(cfg, max_chunks=3)
    elif a.tts:
        rc = tts.run(cfg)
    elif a.mix:
        rc = mix.run(cfg)
    elif a.verify:
        rc = verify.run(cfg)
    elif a.all:
        rc = run_all(cfg)
    else:
        rc = interactive(cfg)
    return 0 if rc is None else rc


if __name__ == "__main__":
    raise SystemExit(main())
