# -*- coding: utf-8 -*-
"""出厂校验：不看波形图，一条一条量。只用标准库 ＋ ffprobe。

为什么要量而不是听
----------------
耳朵能判「像不像」，判不了「旁白是不是从 2.0 秒开始」「淡出是不是真的在降」。
这两件事量出来是确定的数，听出来只能靠感觉。

三条判据写错过的教训（写在这里，免得下次又按错的方式量）
----------------------------------------------------
1. **静音判据不能写死一个绝对 dB**。音乐垫本身就压在 −46 dBFS 左右，
   写死 −45 dB 会把「只有音乐」的正常段落全判成静音。
   ⇒ 用相对阈值，而且「旁白有没有长空隙」要**单独拿旁白文件去量** ——
   成片里有音乐垫着，本来就不该出现绝对静音。
2. **淡入淡出不能用「两格相减」判**。只取两格正好卡在音乐的一个重音上，
   会得出「后一格更响」的假结论。⇒ 用回归斜率判趋势，另加一条幅度判据。
3. **判淡出的取窗长度必须等于淡出自己的长度**。淡出 5 秒却只量末 3 秒，
   前 2 秒扔在窗外，首格落在强拍还是弱拍上直接决定过不过线。
   同一部片子：3 秒窗 14.9 dB（差 0.1 判失败）、5 秒窗 16.6 dB（过线）。
   门槛一个字没改，改的是「量哪个窗口」。
4. **淡出的「淡出前」基准不能用窗内首格**。首格落在音乐的哪一拍上是随机的。
   有一条片首格 −64.3 dB、紧邻的第二格 −55.8 dB，相差 8.5 dB；拿首格减末格
   得 14.997 dB，离门槛差 0.003。设计上被淡出逼到静音的是**末格**，起点没有
   这个约束 ⇒ 基准改取窗内最响格（同一条片 23.48 dB）。
5. **淡入的格宽必须小于淡入长度**。淡入只有 0.3 秒，用 0.5 秒的格去量，整段
   淡入挤在一格里，永远量出 0；而把窗拉到 3 秒，量到的其实是 2 秒后的**人声
   进场**（+11.3 dB/秒），不是淡入本身（0.1 秒格上是 +81.6 dB/秒）。
   淡入的起点是文件第 0 秒，本来就该接近静音 ⇒ 这一条用首格当基准是对的。
"""
import io
import json
import os

from . import media, project, tts, ui

GRID = 0.5           # 逐格电平的格宽（秒）
HOP = 0.05           # 找空隙的帧长（秒）
FADE_GRID = 0.1      # 判淡入的格宽。必须小于淡入长度，否则整段挤在一格里
GAP_BELOW = 30.0     # 比有声段中位低这么多算静音
LONG_GAP = 1.5       # 超过这么久算异常空隙
BED_GAP = 3.0        # 音乐垫断开超过这么久算异常
FADE_DB = 15.0       # 淡入要涨这么多、淡出要降这么多
FADE_SLOPE = 3.0     # 淡入淡出的最小斜率（dB/秒）


def _fmt(seq, n=12):
    return u"  ".join(u"%.1f" % v for v in seq[:n])


def run(cfg):
    ui.title(u"第三步 / 出厂校验")
    outdir = project.out_dir(cfg)
    wav = os.path.join(outdir, u"有声故事.wav")
    if not os.path.isfile(wav):
        ui.bad(u"还没有成片：%s" % wav)
        ui.info(u"先跑第二步。")
        return 2

    rec = {}
    rp = os.path.join(outdir, u"_混音记录.json")
    if os.path.isfile(rp):
        rec = json.load(io.open(rp, encoding="utf-8"))

    nar = tts.narration_wav(cfg)
    has_music = bool(rec.get("music_start_sec"))
    lead = float(rec.get("lead", 0.0))
    tail = float(rec.get("tail", 0.0))
    nar_sec = float(rec.get("nar_sec", 0.0))
    bed_target = float(rec.get("bed_target_db",
                               cfg["narration_db"] - cfg["bed_below_db"]))
    fade_out = float(rec.get("fade_out", cfg["fade_out"]))

    a, nch, sr = media.read_pcm(wav)
    total = len(a) / float(sr * nch)
    peak, clipped = media.peak_of(a)
    st = media.stream_info(wav)

    ui.kv(u"成片", wav)
    ui.kv(u"", u"%.3f 秒 ｜ %d 样本/声道 ｜ %d Hz ｜ %d 声道 ｜ %s"
          % (total, len(a) // max(nch, 1), sr, nch,
             st.get("codec_name", u"?")))
    if rec:
        ui.kv(u"混音记录", u"旁白目标 %.1f dBFS ｜ 音乐垫目标 %.1f dBFS"
              % (float(rec.get("nar_target_db", -22.0)), bed_target))

    checks = []

    def chk(name, passed, detail=u""):
        checks.append({"name": name, "pass": bool(passed)})
        if detail:
            ui.say(u"")
        ui.say(u"  %s  %s" % (u"[通过]" if passed else u"[不通过]", name))
        if detail:
            ui.say(u"        " + detail)

    ui.say(u"")
    chk(u"采样率 %d Hz" % int(cfg["sample_rate"]),
        st.get("sample_rate") == str(int(cfg["sample_rate"])),
        u"实数 %s Hz" % st.get("sample_rate"))
    chk(u"立体声", nch == 2, u"实数 %d 声道" % nch)

    want = lead + nar_sec + tail
    chk(u"时长 %.1f 秒 ±1" % want, abs(total - want) <= 1.0,
        u"实数 %.2f 秒（引子 %.1f ＋ 旁白 %.2f ＋ 收尾 %.1f）"
        % (total, lead, nar_sec, tail))

    ui.say(u"")
    ui.say(u"  [峰值] %.4f（%.2f dBFS），削顶样本 %d 个"
           % (peak, media.db(peak), clipped))
    chk(u"没有削顶", clipped == 0, u"削顶 %d 个样本" % clipped)

    grid = media.block_db(a, nch, sr, GRID)
    intro = []
    if has_music and lead > 0:
        intro = grid[:max(1, int(round(lead / GRID)))]
        im = sum(intro) / float(len(intro))
        ui.say(u"")
        ui.say(u"  [引子] 0~%.1f 秒逐 %.1f 秒：%s" % (lead, GRID, _fmt(intro)))
        chk(u"引子确实有音乐（与音乐垫目标差 ≤12 dB）",
            abs(im - bed_target) <= 12.0,
            u"实测均值 %.2f dBFS，目标 %.1f dBFS，差 %.2f dB"
            % (im, bed_target, im - bed_target))

    # ── 淡入 ────────────────────────────────────────────
    # 窗长＝淡入长度 ＋ 1 格。淡入只有 0.3 秒，格宽用 0.5 秒会把整段挤进一格，
    # 量出来永远是 0；窗拉到 3 秒又会把 2 秒后的人声进场算进来。
    fade_in = float(cfg["fade_in"])
    span_in = min(total, fade_in + FADE_GRID)
    # 只截头部这一小段去量，不必为 0.4 秒把整条片按 0.1 秒重算一遍
    head = a[:int(round(span_in * sr)) * nch]
    fin = media.block_db(head, nch, sr, FADE_GRID)
    nin = max(3, int(round(span_in / FADE_GRID)))
    fin = fin[:nin] if len(fin) >= nin else fin
    sin = media.trend(fin, FADE_GRID)
    rise = fin[-1] - fin[0]
    ui.say(u"")
    ui.say(u"  [淡入] 头 %.1f 秒（＝淡入 %.2f 秒 ＋ 1 格）逐 %.1f 秒：%s"
           % (span_in, fade_in, FADE_GRID, _fmt(fin)))
    chk(u"淡入是递增的（斜率 ≥ +%.0f dB/秒，且首末差 ≥%.0f dB）"
        % (FADE_SLOPE, FADE_DB),
        sin >= FADE_SLOPE and rise >= FADE_DB,
        u"斜率 %+.2f dB/秒，首格 %.1f → 末格 %.1f dB（涨 %.1f dB）"
        % (sin, fin[0], fin[-1], rise))

    # ── 淡出 ────────────────────────────────────────────
    # 窗长＝淡出长度。「淡出前」的基准取窗内最响格，不取首格：
    # 首格踩在弱奏上会平白少掉 8 dB，同一部片子能差 0.003 dB 判失败。
    fo_span = min(fade_out, total)
    nfo = max(2, int(round(fo_span / GRID)))
    fout = grid[len(grid) - nfo:] if len(grid) >= nfo else grid[:]
    sout = media.trend(fout, GRID)
    fout_peak = max(fout)
    drop = fout_peak - fout[-1]
    ui.say(u"")
    ui.say(u"  [淡出] 末 %.1f 秒（＝淡出实际长度）逐 %.1f 秒：%s"
           % (fo_span, GRID, _fmt(fout)))
    ui.say(u"        首格 %.1f dB，窗内最响格 %.1f dB（第 %.1f 秒处）"
           % (fout[0], fout_peak, fout.index(fout_peak) * GRID))
    chk(u"淡出是递减的（斜率 ≤ −%.0f dB/秒，且最响格到末格降 ≥%.0f dB）"
        % (FADE_SLOPE, FADE_DB),
        sout <= -FADE_SLOPE and drop >= FADE_DB,
        u"斜率 %+.2f dB/秒，最响格 %.1f → 末格 %.1f dB（降 %.1f dB）"
        % (sout, fout_peak, fout[-1], drop))

    fine = media.block_db(a, nch, sr, HOP) if has_music else []

    if has_music and lead > 0 and intro:
        base = sum(intro) / float(len(intro))
        thr = base + 8.0
        onset = None
        for i, v in enumerate(fine):
            if v > thr:
                onset = i * HOP
                break
        ui.say(u"")
        ui.say(u"  [旁白进场] 以引子均值 %.1f dB 为基准，阈值 %.1f dB"
               % (base, thr))
        chk(u"旁白在引子结束处进场（%.1f~%.1f 秒）"
            % (max(0.0, lead - 0.2), lead + 0.4),
            onset is not None and (lead - 0.2) <= onset <= (lead + 0.4),
            u"实测 %s" % (u"%.2f 秒" % onset if onset is not None else u"没找到"))

    # 旁白的空隙：拿旁白文件自己量，不在成片里量（成片有音乐垫着）
    if os.path.isfile(nar):
        na, nnch, nsr = media.read_pcm(nar)
        ng = media.block_db(na, nnch, nsr, HOP)
        voiced = [v for v in ng if v > -60.0]
        med = sorted(voiced)[int(len(voiced) * 0.5)] if voiced else -60.0
        nthr = med - GAP_BELOW
        gaps = media.find_gaps(ng, HOP, nthr)
        long_gaps = [g for g in gaps if g[1] >= LONG_GAP]
        ui.say(u"")
        ui.say(u"  [旁白空隙] 有声段中位 %.1f dB，静音阈值 %.1f dB"
               % (med, nthr))
        ui.say(u"        静音段 %d 处，最长 %.2f 秒，超过 %.1f 秒的 %d 处"
               % (len(gaps), max([g[1] for g in gaps] or [0.0]), LONG_GAP,
                  len(long_gaps)))
        for s, d in sorted(long_gaps, key=lambda x: -x[1])[:5]:
            ui.say(u"          %.2f ~ %.2f 秒（%.2f 秒）" % (s, s + d, d))
        chk(u"旁白没有超过 %.1f 秒的空隙" % LONG_GAP, not long_gaps,
            u"最长 %.2f 秒" % max([g[1] for g in gaps] or [0.0]))

    if has_music:
        bthr = bed_target - 12.0
        bgaps = [g for g in media.find_gaps(fine, HOP, bthr) if g[1] >= BED_GAP]
        ui.say(u"")
        ui.say(u"  [音乐垫] 低于 %.1f dB 且超过 %.0f 秒的段 %d 处"
               % (bthr, BED_GAP, len(bgaps)))
        for s, d in sorted(bgaps, key=lambda x: -x[1])[:5]:
            ui.say(u"          %.2f ~ %.2f 秒（%.2f 秒）" % (s, s + d, d))
        chk(u"音乐垫没有超过 %.0f 秒的中断" % BED_GAP, not bgaps,
            u"最长中断 %.2f 秒" % max([g[1] for g in bgaps] or [0.0]))

    bad = [c for c in checks if not c["pass"]]
    ui.say(u"")
    ui.rule(u"-")
    ui.say(u"  结论：%s（共 %d 条，过 %d 条）"
           % (u"全部通过" if not bad else u"%d 条没过" % len(bad),
              len(checks), len(checks) - len(bad)))
    ui.rule(u"-")

    out = {"file": wav, "sec": round(total, 3), "sr": sr, "channels": nch,
           "peak": round(peak, 5), "peak_db": round(media.db(peak), 2),
           "clipped_samples": clipped,
           "has_music": has_music, "lead": lead, "tail": tail,
           "nar_sec": nar_sec, "bed_target_db": bed_target,
           "fade_in_span": round(span_in, 2),
           "fade_in_slope_db_s": round(sin, 2),
           "fade_in_rise_db": round(rise, 2),
           "fade_out_span": round(fo_span, 2),
           "fade_out_slope_db_s": round(sout, 2),
           "fade_out_first_db": round(fout[0], 2),
           "fade_out_peak_db": round(fout_peak, 2),
           "fade_out_last_db": round(fout[-1], 2),
           "fade_out_drop_db": round(drop, 2),
           "checks": checks, "all_pass": not bad}
    with io.open(os.path.join(outdir, u"_出厂校验.json"), "w",
                 encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    ui.say(u"")
    ui.info(u"报告 -> %s" % os.path.join(outdir, u"_出厂校验.json"))
    return 0 if not bad else 1
