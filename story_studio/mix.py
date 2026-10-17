# -*- coding: utf-8 -*-
"""合成成片：把旁白和配乐压成一条能直接放给孩子听的片子。全程 ffmpeg。

结构是固定的三段
----------------
    引子 2 秒（只有音乐） ＋ 旁白 ＋ 收尾 6 秒（只有音乐）

为什么不是「音乐从头铺到尾」：睡前故事需要一点进门和退场的时间。
2 秒刚好够孩子安静下来，6 秒够一句「晚安」落地。这两个数是听出来的，
不是算出来的，所以在 config.json 里，你可以改。

电平按相对关系定，不给绝对值
--------------------------
旁白先归一到 −22 dBFS 均值，音乐垫**再比旁白低 24 dB**。
只给一边一个数是不够的：旁白调轻了，音乐不变，音乐就盖过人声了。
两边都量、按差值定，换任何素材都成立。
"""
import io
import json
import os

from . import media, project, tts, ui

MUSIC_REF = -20.0     # 每段配乐先各自归一到这个均值，再统一压到音乐垫目标
HEAD = 2.0            # 「引子」长度。选起点时直接按这 2 秒有多响来排
HEAD_STEP = 6.0       # 粗扫起点的步长
HEAD_SHORT = 3        # 粗扫之后进决赛圈的候选数
SEG_TOL = 3.0         # 取用段落在「稳态均值」多少 dB 之内算合格
SEG_PROBE = 60.0      # 决赛圈里量多长一段
XFADE = 6.0           # 多个配乐文件之间的交叉淡接
LOOP_XFADE = 4.0      # 配乐不够长时，循环接头的交叉淡接
MIN_LOOP_SEC = 12.0   # 比这还短的配乐没法循环，直接报错


def _pick_start(path, dur, slack):
    """挑从第几秒开始用这段配乐。

    ⚠️ 判据必须是「头 2 秒有多响」，不能只看整段均值。
       ACE-Step 那种曲子前 3 分钟是渐强的，整段均值 −17 dB 的曲子，
       头 2 秒可能只有 −41 dB，引子就成了死寂。要量什么就按什么选，
       别拿更长的窗口当代理。
    """
    limit = min(dur * 0.45, slack)
    if limit < HEAD_STEP:
        head = media.mean_db(path, ss=0.0, t=HEAD)
        return 0.0, head
    body_lo = dur * 0.35
    body_hi = dur * 0.95
    body = media.mean_db(path, ss=body_lo, t=max(1.0, body_hi - body_lo))

    cands = []
    ss = 0.0
    while ss + HEAD <= limit:
        cands.append((media.mean_db(path, ss=ss, t=HEAD), ss))
        ss += HEAD_STEP
    if not cands:
        return 0.0, media.mean_db(path, ss=0.0, t=HEAD)
    cands.sort(key=lambda c: -c[0])

    for head, c_ss in cands[:HEAD_SHORT]:
        seg = media.mean_db(path, ss=c_ss, t=min(SEG_PROBE, dur - c_ss))
        tag = u"合格" if seg >= body - SEG_TOL else u"偏弱"
        ui.info(u"起点 %5.1f 秒：头 %.0f 秒 %.1f dB ｜ 近 %.0f 秒 %.1f dB"
                u"（稳态 %.1f）%s"
                % (c_ss, HEAD, head, SEG_PROBE, seg, body, tag))
        if seg >= body - SEG_TOL:
            return c_ss, head
    ui.warn(u"候选都不合格，退回从 0 秒开始用")
    return 0.0, cands[0][0]


def _reps_needed(bed_dur, total):
    """循环几遍才够长。每次循环吃掉 LOOP_XFADE 秒的接头。"""
    if bed_dur >= total:
        return 1
    reps = 1
    while reps < 40:
        span = reps * bed_dur - (reps - 1) * LOOP_XFADE
        if span >= total:
            return reps
        reps += 1
    return 0


def run(cfg):
    ui.title(u"第二步 / 合成成片")
    nar = tts.narration_wav(cfg)
    if not os.path.isfile(nar):
        ui.bad(u"还没有旁白：%s" % nar)
        ui.info(u"先跑第一步。")
        return 2

    if not media.have("ffmpeg") or not media.have("ffprobe"):
        ui.bad(u"找不到 ffmpeg。装好之后重开这个窗口")
        return 2

    sr = int(cfg["sample_rate"])
    nar_dur = media.duration(nar)
    musics = project.read_music(cfg)
    lead = float(cfg["lead"]) if musics else 0.0
    tail = float(cfg["tail"]) if musics else 0.0
    total = lead + nar_dur + tail

    ui.kv(u"旁白", u"%s ｜ %.2f 秒" % (os.path.basename(nar), nar_dur))
    if musics:
        for m in musics:
            ui.kv(u"配乐", u"%s ｜ %.2f 秒"
                  % (os.path.basename(m), media.duration(m)))
        ui.kv(u"结构", u"引子 %.1f ＋ 旁白 %.2f ＋ 收尾 %.1f = %.2f 秒"
              % (lead, nar_dur, tail, total))
    else:
        ui.kv(u"配乐", u"没放，只出旁白")
        ui.kv(u"结构", u"旁白 %.2f 秒" % total)

    # ── 电平 ───────────────────────────────────────────
    nar_mean = media.mean_db(nar)
    nar_gain = float(cfg["narration_db"]) - nar_mean
    bed_target = float(cfg["narration_db"]) - float(cfg["bed_below_db"])
    ui.say(u"")
    ui.info(u"旁白均值 %.2f dBFS，归一到 %.1f dBFS（%+.2f dB）"
            % (nar_mean, float(cfg["narration_db"]), nar_gain))
    if musics:
        ui.info(u"音乐垫 %.1f dBFS，比旁白低 %.0f dB"
                % (bed_target, float(cfg["bed_below_db"])))

    inputs = [nar]
    chains = []

    nar_chain = (
        u"[0:a]aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        u"volume=%.2fdB,adelay=%d|%d,apad=whole_dur=%.3f[nar]"
        % (sr, nar_gain, int(round(lead * 1000)), int(round(lead * 1000)),
           total))
    chains.append(nar_chain)

    if not musics:
        # 没有配乐时也要淡入淡出，否则开头一下炸出来、结尾一刀切。
        chains.append(u"[nar]afade=t=in:st=0:d=0.30,"
                      u"afade=t=out:st=%.3f:d=%.2f[out]"
                      % (max(0.0, total - float(cfg["fade_out"])),
                         float(cfg["fade_out"])))
        bed_info = {}
    else:
        # ① 每段配乐各自归一，并把起点抬到挑出来的位置
        #
        # ⚠️ 「能跳过多少秒」不能只按「配乐总长 − 成片长度」算。
        #    单段 482 秒 < 成片 501 秒，一减就是负数，被 max(0, ...) 夹成 0，
        #    于是「跳过弱奏开头」这件事被静悄悄取消，引子又回到死寂。
        #    正确的算法是先把「循环几遍之后到底有多少可用时长」算出来，
        #    再拿它减成片长度。
        raw_span = sum(media.duration(m) for m in musics)
        base_bed = raw_span - XFADE * (len(musics) - 1)
        reps0 = _reps_needed(base_bed, total)
        usable = (reps0 * base_bed - (reps0 - 1) * LOOP_XFADE) if reps0 else 0
        slack_total = max(0.0, usable - total)
        slack_each = slack_total / float(len(musics))
        starts, gains, heads = [], [], []
        ui.say(u"")
        for i, m in enumerate(musics):
            d = media.duration(m)
            ss, head = _pick_start(m, d, slack_each)
            mm = media.mean_db(m, ss=ss, t=min(total, max(1.0, d - ss)))
            g = MUSIC_REF - mm
            starts.append(ss)
            gains.append(g)
            heads.append(round(head, 2))
            ui.info(u"%s ⇒ 从 %.1f 秒起，归一 %+.2f dB"
                    % (os.path.basename(m), ss, g))
            inputs.append(m)
            chains.append(
                u"[%d:a]aresample=%d,"
                u"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                u"atrim=start=%.3f,asetpts=N/SR/TB,volume=%.2fdB[m%d]"
                % (i + 1, sr, ss, g, i))

        # ② 多个文件之间交叉淡接
        if len(musics) == 1:
            chains.append(u"[m0]anull[cat]")
        else:
            prev = u"m0"
            for i in range(1, len(musics)):
                chains.append(u"[%s][m%d]acrossfade=d=%.2f:c1=tri:c2=tri[cf%d]"
                              % (prev, i, XFADE, i))
                prev = u"cf%d" % i
            chains.append(u"[%s]anull[cat]" % prev)

        # ③ 不够长就循环几遍。用 asplit 复制同一路流再交叉淡接，
        #    不用 -stream_loop：那样接头是硬切，会有咔哒。
        #    可用长度要扣掉「挑起点时跳过的那些秒」，否则会误判成够长。
        bed_dur = (sum(media.duration(m) - s for m, s in zip(musics, starts))
                   - XFADE * (len(musics) - 1))
        if bed_dur < MIN_LOOP_SEC and bed_dur < total:
            ui.bad(u"配乐只有 %.1f 秒，太短了没法循环。换一段长一点的"
                   % bed_dur)
            return 2
        reps = _reps_needed(bed_dur, total)
        if reps == 0:
            ui.bad(u"配乐太短，循环也算不出够长的音垫")
            return 2
        if reps > 1:
            ui.info(u"配乐合计 %.1f 秒，不够 %.1f 秒，循环 %d 遍（接头 %.0f 秒交叉淡接）"
                    % (bed_dur, total, reps, LOOP_XFADE))
            chains.append(u"[cat]asplit=%d%s"
                          % (reps, u"".join(u"[c%d]" % i for i in range(reps))))
            prev = u"c0"
            for i in range(1, reps):
                chains.append(u"[%s][c%d]acrossfade=d=%.2f:c1=tri:c2=tri[lp%d]"
                              % (prev, i, LOOP_XFADE, i))
                prev = u"lp%d" % i
            chains.append(u"[%s]anull[long]" % prev)
        else:
            chains.append(u"[cat]anull[long]")

        bed_gain = bed_target - MUSIC_REF
        fade_st = max(0.0, total - float(cfg["fade_out"]))
        chains.append(
            u"[long]volume=%.2fdB,apad=whole_dur=%.3f,atrim=0:%.3f,"
            u"asetpts=N/SR/TB,afade=t=in:st=0:d=%.2f,"
            u"afade=t=out:st=%.2f:d=%.2f[mus]"
            % (bed_gain, total, total, float(cfg["fade_in"]), fade_st,
               float(cfg["fade_out"])))
        chains.append(
            u"[nar][mus]amix=inputs=2:duration=longest:normalize=0[mix];"
            u"[mix]alimiter=limit=%.2f:level=disabled,"
            u"afade=t=in:st=0:d=0.30[out]"
            % float(cfg["limiter"]))
        bed_info = {"music_start_sec": [round(s, 2) for s in starts],
                    "music_gain_db": [round(g, 2) for g in gains],
                    "music_head_db": heads, "bed_target_db": round(bed_target, 2),
                    "bed_gain_db": round(bed_gain, 2), "loop_reps": reps,
                    "bed_raw_sec": round(bed_dur, 2)}

    outdir = project.out_dir(cfg)
    wav = os.path.join(outdir, u"有声故事.wav")
    mp3 = os.path.join(outdir, u"有声故事.mp3")
    fc = u";".join(chains)

    ui.say(u"")
    ui.info(u"混音：淡入 %.2f 秒、淡出 %.2f 秒、限幅 %.2f"
            % (float(cfg["fade_in"]), float(cfg["fade_out"]),
               float(cfg["limiter"])))
    ins = []
    for f in inputs:
        ins += ["-i", f]
    media.need(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + ins
               + ["-filter_complex", fc, "-map", "[out]",
                  "-ar", str(sr), "-ac", "2", "-c:a", "pcm_s16le", wav])
    media.need(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", wav, "-c:a", "libmp3lame", "-b:a", "192k", mp3])

    rec = {"narration": nar, "nar_sec": round(nar_dur, 2),
           "nar_mean_db": round(nar_mean, 2),
           "nar_gain_db": round(nar_gain, 2),
           "nar_target_db": float(cfg["narration_db"]),
           "speed": float(cfg["speed"]),
           "lead": lead, "tail": tail,
           "fade_in": float(cfg["fade_in"]),
           "fade_out": float(cfg["fade_out"]),
           "limiter": float(cfg["limiter"]),
           "sample_rate": sr,
           "total_sec": round(media.duration(wav), 2),
           "wav": wav, "mp3": mp3,
           "wav_bytes": os.path.getsize(wav),
           "mp3_bytes": os.path.getsize(mp3)}
    rec.update(bed_info)
    with io.open(os.path.join(outdir, u"_混音记录.json"), "w",
                 encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)

    ui.say(u"")
    ui.ok(u"成片 %.2f 秒（%.0f 分 %02.0f 秒）"
          % (rec["total_sec"], rec["total_sec"] // 60,
             rec["total_sec"] % 60))
    ui.kv(u"wav", u"%s ｜ %.2f MB" % (wav, rec["wav_bytes"] / 1048576.0))
    ui.kv(u"mp3", u"%s ｜ %.2f MB" % (mp3, rec["mp3_bytes"] / 1048576.0))
    ui.say(u"")
    ui.info(u"下一步跑一遍出厂校验，一条一条量过去。")
    return 0
