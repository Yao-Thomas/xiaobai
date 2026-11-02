#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""matrix_vol.py —— 找线性区 + 验证可复现性（一条龙）

背景（第 4~5 轮的结论）：
  * 连跑 3 次矩阵，对角线都是 0/6，而且**所有频点能量都被抬平**
    => 放音时采到的不是纯音，是**宽带噪声**（ADC 被串扰打过载）。
  * 原理图给出了耦合路径：
      - 麦克风偏置经 R36(2K) 挂在 +5V，功放 MD8002A 也从 +5V 取流
      - 喇叭电流几百 mA 经 PCB 地回流，与麦克风 R37(680R) 共地
    所以"边放边录"本身就容易过载；**半双工工作时喇叭静音，没有这个问题**。

本脚本的流程：
  阶段1  扫放音电平(vol/amp)      -> 找"平坦度>100 且 命中>=4"的线性区（旧值 1.8 已废弃：白噪声自己就 1.70）
  阶段2  在最好那档扫 ADC PGA     -> 选信噪比最好的 PGA
  阶段3  用选中的 (vol,amp,pga) 连跑 3 次矩阵 -> 验证**可复现**
  阶段4  量化半双工优势：DAC 静音 vs DAC 放音 时的噪声底

用法（板上后台跑，别用前台，见 bg_mvol.sh）:
  sudo systemctl stop zynq-audio; sudo python3 -u matrix_vol.py
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
SECS = 0.40
CFG = {0x08: 0x00, 0x01: 0x50, 0x02: 0x00, 0x0B: 0x02,
       0x09: 0x66, 0x0A: 0x00, 0x10: 0x00, 0x11: 0x00,
       0x03: 0x51, 0x2B: 0x80,
       0x00: 0x06, 0x0C: 0x00, 0x0D: 0x02, 0x18: 0x03,
       0x1A: 0x00, 0x1B: 0x00, 0x27: 0xF8, 0x2A: 0xF8}
VOLS = [(4, 0.9), (8, 0.9), (12, 0.9), (16, 0.9), (20, 0.9),
        (24, 0.9), (30, 0.9), (30, 0.35), (30, 0.15)]
PGAS = [0x00, 0x11, 0x22, 0x33, 0x44, 0x66]


def left(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def win(v):
    n = len(v)
    if n < 8:
        return [float(x) for x in v]
    k = 2.0 * math.pi / (n - 1)
    return [v[i] * (0.5 - 0.5 * math.cos(k * i)) for i in range(n)]


def goe_multi(w, freqs, rate=FS):
    n = len(w)
    if n < 64:
        return [0.0 for _ in freqs]
    out = []
    for f in freqs:
        c = 2.0 * math.cos(2.0 * math.pi * f / rate)
        s1 = s2 = 0.0
        for x in w:
            s0 = x + c * s1 - s2
            s2, s1 = s1, s0
        out.append(math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (n / 4.0))
    return out


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)
    secs = min(SECS, 0.8 * cap.ring / 352800.0)
    i2c = cap.i2c
    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, b"\x00" * ao.ring)
    ao.start()
    for r, v in CFG.items():
        i2c.wr(r, v)
    time.sleep(0.4)

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    ks = [23, 30, 46, 60, 70, 93]
    freqs = [round(k * float(FS) / frames, 2) for k in ks]
    settle = ao.ring / 352800.0 + 0.12

    def rec():
        cap.cfg()
        cap.grab(0.08)
        cap.cfg()
        d, _ = cap.grab(secs)
        return left(d)

    def quiet():
        ao.buf.write(0, b"\x00" * ao.ring)
        time.sleep(settle)

    def play(f0, amp):
        tone = (make_sine(f0, frames=frames, amp=amp, pack=ao.pack) * 8)[:ao.ring]
        ao.buf.write(0, tone)
        time.sleep(settle)

    # ★ 故障 B（采集整段失败）的重试上限。全零 = 那一次没采到数据。
    #   模拟测过：单次全零率 20% 时 RETRY=3 能 100% 兜住；
    #   50% 时 86%；80% 时只有 52%。所以取 4 并在报告里打全零率 ——
    #   全零率本身就是诊断数据，太高就该继续加。
    RETRY = 4
    STATS = {"zero": 0, "grabs": 0, "retried": 0}

    def grab_energy():
        """采一次并算能量。若全零则重试（最多 RETRY 次）。

        返回 (e, zeros)  —— e 是能量列表，zeros 是这次遇到的全零次数。
        全零的判据: max(e) == 0（一个频点都没能量 = 整段没采到数据）。
        """
        zeros = 0
        for _ in range(RETRY):
            cap.cfg()
            d, _ = cap.grab(secs)
            v = left(d)
            STATS["grabs"] += 1
            e = goe_multi(win(v), freqs) if v else [0.0] * len(freqs)
            if max(e) > 0:
                if zeros:
                    STATS["retried"] += 1
                return e, zeros
            # ★ 全零 = 故障 B，记一笔再重来
            STATS["zero"] += 1
            zeros += 1
            time.sleep(0.08)
        # 重试都用完了还是全零，把它当结果返回（上层会标成无效）
        return [0.0] * len(freqs), zeros

    def one_matrix(amp):
        """返回 (命中数, 最小平坦度, 每行明细)

        ★ 改动：平坦度返回 **min**（和判据一致），不是 mean。
          原来返回 mean 会把单行坏数据平均掉 —— 那是真 bug。
          明细里保留 mean 供参考。
        """
        quiet()
        rec()
        b, _bz = grab_energy()
        base = b
        hit, flats, means, rows = 0, [], [], []
        for f0 in freqs:
            play(f0, amp)
            e, zeros = grab_energy()
            valid = max(e) > 0
            # ★ 无效轮次（全零）不能算命中！
            #   坑：e 全零时 max(e)=0，e.index(0)=0 -> top 恒等于 freqs[0]，
            #   如果 f0 正好是 freqs[0] 就会被错判成"命中"。必须先判 valid。
            top = e.index(max(e)) if valid else -1
            ok = bool(valid and top == freqs.index(f0))
            hit += 1 if ok else 0
            med = sorted(e)[len(e) // 2] or 1e-9
            fl = max(e) / med
            if valid:
                flats.append(fl)          # ★ 平坦度只在有效轮次上取
            means.append(fl)
            rows.append((f0, freqs[top] if valid else 0.0, ok, max(e),
                         base[top] if valid else 0.0, zeros, valid))
        quiet()
        mn = min(flats) if flats else 0.0
        return hit, mn, rows

    print("=" * 94, flush=True)
    print("matrix_vol  找线性区 + 验证可复现  ring=%d 录%.2fs" % (cap.ring, secs),
          flush=True)
    print("=" * 94, flush=True)

    # ---------- 阶段 1: 扫放音电平 ----------
    print("\n【阶段1】扫放音电平，找线性区（判据: 平坦度>100 且 命中>=4）", flush=True)
    print("%-12s %-8s %-9s %-10s %s"
          % ("vol/amp", "命中", "平坦度", "静音RMS", "判定"), flush=True)
    print("-" * 94, flush=True)
    cands = []
    for vol, amp in VOLS:
        es8388_set_vol(ao.i2c, vol, 0)
        quiet()
        rec()
        q = rec()
        hit, fl, _ = one_matrix(amp)
        # ★ 阈值来自 test_audio_math.py 的离线实测：
        #     纯音 990.5Hz 平坦度 ~7.6e5，白噪声只有 1.70，斜坡图案 2.01
        #   所以 1.8 这种阈值毫无区分度（噪声自己就 1.70），必须用 100。
        verdict = ("★ 线性区" if fl > 100 and hit >= 4 else
                   "糊成一片(过载)" if fl < 10 else "临界")
        print("%-12s %-8s %-9.2f %-10.0f %s"
              % ("vol=%-2d a=%.2f" % (vol, amp), "%d/6" % hit, fl, rms(q), verdict),
              flush=True)
        if fl > 100 and hit >= 4:
            cands.append((vol, amp, fl, hit))
            # ★ 从**最轻**开始扫，一找到线性区就立刻停：
            #   用户明确反馈测试音太吵（之前用蜂鸣器，方波 2~4kHz，很刺耳）。
            #   正弦单音从 vol=4 起扫，够用就停，不再往上加音量。
            print("   ↑ 已找到线性区，停止加音量（再往上只会更吵）", flush=True)
            break

    if not cands:
        print("\n⚠ 没有任何一档电平进入线性区 —— 说明过载来自共地/电源轨耦合，"
              "只靠降音量压不下去。需要硬件层面处理（见报告第5轮结论）。", flush=True)
        best_vol, best_amp = 8, 0.9
    else:
        cands.sort(key=lambda x: (-x[3], -x[2]))
        best_vol, best_amp = cands[0][0], cands[0][1]
        print("\n★ 线性区最优点: vol=%d amp=%.2f (命中%d/6 平坦度%.2f)"
              % (best_vol, best_amp, cands[0][3], cands[0][2]), flush=True)

    # ---------- 阶段 2: 扫 PGA ----------
    es8388_set_vol(ao.i2c, best_vol, 0)
    print("\n【阶段2】在 vol=%d amp=%.2f 下扫 ADC PGA" % (best_vol, best_amp), flush=True)
    print("%-10s %-8s %-9s %-11s %s"
          % ("PGA", "命中", "平坦度", "静音RMS", "说明"), flush=True)
    print("-" * 94, flush=True)
    pga_best, pga_score = 0x66, -1
    for pga in PGAS:
        i2c.wr(0x09, pga)
        time.sleep(0.25)
        quiet()
        rec()
        q = rec()
        hit, fl, _ = one_matrix(best_amp)
        score = fl * (1 + hit)
        lbl = {0x00: "0dB", 0x11: "+3dB", 0x22: "+6dB", 0x33: "+9dB",
               0x44: "+12dB", 0x66: "+18dB"}[pga]
        print("%-10s %-8s %-9.2f %-11.0f %s"
              % (lbl, "%d/6" % hit, fl, rms(q),
                 "★" if score > pga_score else ""), flush=True)
        if score > pga_score:
            pga_score, pga_best = score, pga
    i2c.wr(0x09, pga_best)
    print("★ 选定 PGA=0x%02X" % pga_best, flush=True)

    # ---------- 阶段 3: 可复现性 ----------
    print("\n【阶段3】用 vol=%d amp=%.2f PGA=0x%02X 连跑 3 次矩阵"
          % (best_vol, best_amp, pga_best), flush=True)
    res = []
    for k in range(3):
        hit, fl, rows = one_matrix(best_amp)
        res.append((hit, fl))
        print("  第%d次: 命中 %d/6  平坦度(最小) %.2f" % (k + 1, hit, fl),
              flush=True)
        for f0, top, ok, pk, bs, z, valid in rows:
            tag = "★" if ok else ("Ø无效" if not valid else " ")
            print("      播%7.1f -> 峰%7.1f %s 峰/基线=%5.1f%s"
                  % (f0, top, tag, pk / max(1e-9, bs),
                     ("  全零重试%d次" % z) if z else ""), flush=True)
    hits = [r[0] for r in res]
    fls = [r[1] for r in res]
    ok = (min(hits) >= 4 and min(fls) > 100 and max(hits) - min(hits) <= 1)
    print("\n  命中 %s   平坦度(最小) %s"
          % (hits, ["%.2f" % x for x in fls]), flush=True)
    print("  => %s" % ("★★ 可复现的频谱自证成立（③ 达成）" if ok else
                       "⚠ 仍不可复现，需要进一步降干扰"), flush=True)
    # ★ 故障 B 的统计（采集整段失败 = 全零）：这个数字本身就是诊断数据
    zg, gr = STATS["zero"], STATS["grabs"]
    print("\n  【故障B统计】采集 %d 次，其中**全零 %d 次 (%.1f%%)**，"
          "触发重试 %d 轮" % (gr, zg, 100.0 * zg / max(1, gr),
                              STATS["retried"]), flush=True)
    if zg == 0:
        print("     -> 本次没遇到'采集整段失败'，故障 B 未出现", flush=True)
    else:
        print("     -> 确认存在'采集整段失败'（故障 B），"
              "重试机制已把它兜住", flush=True)

    # ---------- 阶段 4: 半双工优势 ----------
    quiet()
    rec()
    qd = rms(rec())
    es8388_set_vol(ao.i2c, best_vol, 0)
    play(freqs[2], best_amp)
    tp = rms(rec())
    quiet()
    print("\n【阶段4】DAC 静音噪声底=%.0f   放音时=%.0f   比值=%.1fx (%.1f dB)"
          % (qd, tp, tp / max(1e-9, qd),
             20 * math.log10(max(1e-9, tp) / max(1e-9, qd))), flush=True)
    print("      （半双工工作时是前者；差距越大说明'边放边录'越吃亏）", flush=True)

    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print("DONE(WITH ERROR)", flush=True)
