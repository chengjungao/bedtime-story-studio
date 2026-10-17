# -*- coding: utf-8 -*-
"""真正跑推理的那一段。**这个文件必须用装了 torch 的解释器跑**。

为什么单独一个文件
------------------
CosyVoice 要 torch（装完 3 GB 起）。把它关在这一个文件里，
项目其余部分就只用标准库，任何 Python 3.8+ 都能跑；
没装环境的机器上也能先做自检、看提示。

四条必须照做的（都是实测撞出来的，不是猜的）
------------------------------------------
1. **prompt_text 必须带 `<|endofprompt|>` 前缀**。
   `cosyvoice/llm/llm.py` 里有两条硬断言（151646 就是那个特殊 token）：
       assert 151646 in text
       assert 151646 in prompt_text
   缺了不是「不出声」，是直接 AssertionError 崩掉。
2. **参考音频 ≤ 30 秒**（`cli/frontend.py:99` 的 assert），超了报错退出，
   不是自动截断。上游这里卡得很死，所以要卡在入口更前面。
3. **每段用 `stream=False`**。文本里带 `<|...|>` 时前端会跳过 text_frontend，
   而分段逻辑就在前端里 —— 开流式等于绕过分段。
4. **仓库根要手动塞进 sys.path**。`cosyvoice` 与 `matcha` 都没有 pip 装进环境，
   Python 3.11 起 `os.chdir` 又不影响 sys.path，光切目录没用。

一个反直觉的默认值：`--gap 0`
---------------------------
官方 `inference_zero_shot` 分段后**直接 yield，段间不插任何静音**，
那点换气声是模型自己产生的。往官方链路里塞一个自己发明的固定静音，
会听出机械感 —— 上一版试过（段间 0.35 秒），作者一听就说不自然。
所以默认 0，要留白得单独做对照，别混进基线。
"""
import argparse
import io
import json
import os
import sys
import time

PREFIX = u"You are a helpful assistant."
EOP = u"<|endofprompt|>"


def log(msg):
    sys.stdout.write(msg + u"\n")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cosyvoice-dir", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ref-text", required=True)
    ap.add_argument("--story", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--speed", type=float, default=0.85)
    ap.add_argument("--fp16", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--max-chunks", type=int, default=0)
    a = ap.parse_args()

    # 下面会 os.chdir(仓库根)，相对路径立刻失效，所以先全部转绝对。
    repo = os.path.abspath(a.cosyvoice_dir)
    a.model = os.path.abspath(a.model)
    a.ref = os.path.abspath(a.ref)
    a.story = os.path.abspath(a.story)
    a.outdir = os.path.abspath(a.outdir)

    if not os.path.isdir(repo):
        log(u"找不到 CosyVoice 源码目录：%s" % repo)
        return 2
    if not os.path.isfile(a.ref):
        log(u"找不到参考录音：%s" % a.ref)
        return 2

    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "third_party", "Matcha-TTS"))
    os.chdir(repo)

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    story = io.open(a.story, encoding="utf-8").read().strip()
    if not story:
        log(u"故事是空的")
        return 2
    os.makedirs(a.outdir, exist_ok=True)

    fp16 = bool(a.fp16) and torch.cuda.is_available()
    if a.fp16 and not fp16:
        log(u"没有可用的 CUDA，fp16 自动关掉（会慢一些，声音一样）")

    log(u"PROG load 正在把模型读进显存，第一次要三十秒上下")
    t0 = time.time()
    cosy = AutoModel(model_dir=a.model, fp16=fp16)
    log(u"PROG load 模型就绪 %.1f 秒" % (time.time() - t0))

    # 用官方同一套分段函数，保证和「整篇丢进去」的分段结果完全一致。
    segs = cosy.frontend.text_normalize(story, split=True)
    log(u"PROG seg 切成 %d 段" % len(segs))
    for i, s in enumerate(segs, 1):
        log(u"  %2d) %3d 字  %s"
            % (i, len(s), s[:26] + (u"…" if len(s) > 26 else u"")))

    prompt_text = PREFIX + EOP + a.ref_text
    n = len(segs) if a.max_chunks <= 0 else min(a.max_chunks, len(segs))
    rows, pieces = [], []
    done = skipped = 0
    bad = []

    for i in range(1, n + 1):
        txt = segs[i - 1]
        p = os.path.join(a.outdir, u"seg_%03d.wav" % i)
        # 断点续传：文件在就跳过。⚠️ 换了参考录音或语速要清空这个目录，
        # 否则会把上一版的段当成这一版拼进去，还不报错。
        if os.path.isfile(p) and os.path.getsize(p) > 1024:
            w, sr = torchaudio.load(p)
            pieces.append(w)
            if a.gap > 0:
                pieces.append(torch.zeros(1, int(a.gap * sr)))
            skipped += 1
            log(u"PROG skip %d/%d 已有，跳过" % (i, n))
            continue
        t1 = time.time()
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        try:
            chunks = [o["tts_speech"] for o in cosy.inference_zero_shot(
                txt, prompt_text, a.ref, stream=False, speed=a.speed)]
        except Exception as e:
            log(u"PROG fail %d/%d %s: %s"
                % (i, n, type(e).__name__, str(e)[:160]))
            rows.append({"idx": i, "ok": False, "err": str(e)[:200]})
            bad.append(i)
            continue
        if not chunks:
            log(u"PROG fail %d/%d 模型没有输出" % (i, n))
            rows.append({"idx": i, "ok": False, "err": "empty"})
            bad.append(i)
            continue
        w = torch.cat(chunks, dim=1)
        torchaudio.save(p, w.cpu(), cosy.sample_rate)
        pieces.append(w)
        if a.gap > 0:
            pieces.append(torch.zeros(1, int(a.gap * cosy.sample_rate)))
        dt = time.time() - t1
        sec = w.shape[-1] / float(cosy.sample_rate)
        peak = (torch.cuda.max_memory_allocated() / 1073741824.0
                if torch.cuda.is_available() else float("nan"))
        done += 1
        log(u"PROG seg %d/%d %d 字 -> %.2f 秒 ｜ %.2f 字/秒 ｜ 耗时 %.1f 秒 ｜ 显存 %.2f GB"
            % (i, n, len(txt), sec, len(txt) / max(sec, 1e-6), dt, peak))
        rows.append({"idx": i, "ok": True, "chars": len(txt),
                     "sec": round(sec, 2),
                     "chars_per_sec": round(len(txt) / max(sec, 1e-6), 2),
                     "wall_sec": round(dt, 1),
                     "peak_vram_gb": None if peak != peak else round(peak, 2),
                     "text": txt, "file": p})

    good = [r for r in rows if r.get("ok")]
    log(u"")
    log(u"新生成 %d 段 ｜ 跳过已有 %d 段 ｜ 失败 %d 段 ｜ 计划 %d 段"
        % (done, skipped, len(bad), n))
    if good:
        tot = sum(r["sec"] for r in good)
        wall = sum(r["wall_sec"] for r in good)
        log(u"共 %.1f 秒音频，耗时 %.1f 秒，整体 RTF %.3f"
            % (tot, wall, wall / max(tot, 1e-6)))

    # ⚠️ 拼全篇的前提是**每一段都成功**。
    #    只看「条数对不对」会把缺了中间段的全篇当成品存下来 ——
    #    不报错、只少内容，最难发现。所以查的是 ok，不是条数。
    full = u""
    if a.max_chunks <= 0 and pieces and len(good) == len(segs) and not bad:
        merged = torch.cat(pieces, dim=1)
        full = os.path.join(a.outdir, u"全篇_拼接.wav")
        torchaudio.save(full, merged.cpu(), cosy.sample_rate)
        log(u"PROG full 全篇 %.2f 秒"
            % (merged.shape[-1] / float(cosy.sample_rate)))
    elif a.max_chunks <= 0:
        log(u"PROG full 没有拼全篇（成功 %d / 计划 %d / 失败 %d）"
            % (len(good), len(segs), len(bad)))

    rec = {"model": a.model, "cosyvoice_dir": repo, "ref": a.ref,
           "ref_text": a.ref_text, "speed": a.speed, "gap": a.gap,
           "fp16": fp16, "sample_rate": cosy.sample_rate,
           "n_segments": len(segs), "segments": segs, "rows": rows,
           "failed": bad, "full": full,
           "done": done, "skipped": skipped}
    with io.open(os.path.join(a.outdir, u"_生成记录.json"), "w",
                 encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return 0 if not bad else 3


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    raise SystemExit(main())
