#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acoustic_selftest.py —— 声学自测闭环（放已知频率 → 录音 → 算频响 → 判定）

════════════════════════════════════════════════════════════════════
这是干什么的
════════════════════════════════════════════════════════════════════
"系统管家小白"要能自己验证自己的音频通路好不好。做法：

    放一个已知频率的纯音（喇叭）
        ↓ 空气中传播
    麦克风录回来
        ↓ 分析
    判断：麦克风听到了吗？频率对吗？信噪比够吗？

这也是 B1（采集通路）的验收手段 —— 光看波形是静音还不够，
要放个音看它能不能收到。

════════════════════════════════════════════════════════════════════
两个必须注意的坑（都踩过）
════════════════════════════════════════════════════════════════════
① 【不能找"能量最大的频率"】
   文档 14_音频勘验 里记录过：基线在 100Hz 有 1.97e17 的市电工频谐波，
   而纯音提升只有 +0.5dB。找最大能量会找到 100Hz，完全错。
   ⇒ 正确做法：算 **play/base 的比值**，比值最大的那个才是纯音。

② 【24 位数据没有符号扩展】
   本板采集的 S24_LE 是"低 3 字节 + 无符号扩展"：
       字节 FE FF FF 00  ->  int32 = 0x00FFFFFE = 16777214
       实际代表 -2（24 位 0xFFFFFE）
   直接当 int32 用会得到巨大的正数，右移 8 位会得到 65535，都是假象。
   ⇒ 必须从 bit23 手动符号扩展。本脚本用 analyze_wav 里同一套逻辑。

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    sudo python3 acoustic_selftest.py                 # 默认 990.53 Hz
    sudo python3 acoustic_selftest.py --freq 1000 --secs 1.5
    sudo python3 acoustic_selftest.py --sweep         # 扫多个频点
    sudo python3 acoustic_selftest.py --vol 40        # 指定音量
"""
import argparse
import array
import ctypes
import json
import math
import os
import struct
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★★★ 2026-10-02 修正：播放和采集用的是【两个不同的设备】
#
#   采集：hw:0,1（es8388-hifi-analog-1），只接受 S24_LE
#   播放：★ 不能用 hw:0,0 —— 实测它只接受 S24_LE，16 位 WAV 会报
#             aplay: set_params:1368: Sample format non available
#         而 plughw:0,0 也失败（Unable to install hw params）。
#         ★ 只有 `default` 能用（退出码 0），音频服务用的也是它（aplay 不带 -D）。
#
#   我第一版把播放写成 `-D hw:0,1` —— 既用错了设备（0,1 是采集），
#   又绕过了 default 的格式转换，所以**声学自测从来没真的播放过**，
#   一直在对一个空的播放设备放音。
CAP_DEV = "hw:0,1"        # 采集设备
PLAY_DEV = "default"      # 播放设备（★ 不要写 hw:0,0）
RATE = 44100
TMP = "/tmp/selftest_cap.wav"

# ★ 静音锁：用户在本人同意之前不许出声，靠这个文件
#   （实测踩过：锁着的时候这个脚本照样放音 —— 因为独立脚本漏了检查）
SILENT_FLAG = "/etc/zynq-silent"

# 文档里用的那个很具体的频率（避开 1kHz 的整数倍干扰）
DEFAULT_FREQ = 990.53


# ---------------------------------------------------------------- 采集
def capture(secs, path=TMP):
    """用 ALSA 录一段 24 位原始数据，返回样本数组（已做符号扩展）

    ★ arecord 的 -d 只接受【整数秒】！传 1.2 会直接报
        arecord: main:677: invalid duration argument '1.2'
      所以要向上取整录，再按需要的样本数截断。
      （踩过一次：整段自测一个字都没跑出来）
    """
    try:
        os.remove(path)
    except OSError:
        pass
    dur = int(math.ceil(secs))
    p = subprocess.run(
        ["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE", "-c", "2",
         "-r", str(RATE), "-d", str(dur), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=dur + 15)
    if p.returncode != 0:
        raise RuntimeError("arecord 失败: %s"
                           % p.stderr.decode(errors="replace").strip()[:200])
    raw = p.stdout
    # 截到需要的长度（每帧 = 2 声道 × 4 字节）
    want = int(secs * RATE) * 2 * 4
    raw = raw[:want]
    a = array.array("i")
    a.frombytes(raw[:len(raw) & ~3])
    # ★ 从 bit23 手动符号扩展（本板的 24 位数据不做扩展）
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    return a


def play_tone(freq, secs, vol=33, amp=0.6):
    """用 aplay 放一个纯音（先合成 WAV）"""
    subprocess.run(["amixer", "-q", "-c", "0", "sset", "Playback", str(vol)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n = int(secs * RATE)
    peak = int(amp * 32767)
    buf = array.array("h")
    for i in range(n):
        v = int(peak * math.sin(2 * math.pi * freq * i / RATE))
        buf.append(v)
        buf.append(v)
    wav = "/tmp/selftest_tone.wav"
    with open(wav, "wb") as f:
        data = buf.tobytes()
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, RATE,
                                      RATE * 4, 4, 16))
        f.write(b"data" + struct.pack("<I", len(data)))
        f.write(data)
    subprocess.run(["aplay", "-q", "-D", PLAY_DEV, wav],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=secs + 10)


# ---------------------------------------------------------------- 分析
def goertzel(samples, freq, rate=RATE):
    """单频能量检测（Goertzel 算法）

    比 FFT 更适合"我只关心某一个频率"的场景，而且不用 numpy。
    """
    n = len(samples)
    if n == 0:
        return 0.0
    k = int(0.5 + n * freq / rate)
    w = 2.0 * math.pi * k / n
    cw = math.cos(w)
    coeff = 2.0 * cw
    s0 = s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return power / (n * n)


def rms(samples):
    if not samples:
        return 0.0
    return math.sqrt(sum(float(x) * x for x in samples) / len(samples))


def dbfs(v, full=8388608.0):
    return 20 * math.log10(v / full) if v > 0 else -999.0


def to_mono(a):
    """立体声 -> 单声道（取左声道；本板右声道是空的）"""
    return a[0::2]


# ---------------------------------------------------------------- 判定
def one_test(freq, secs, vol):
    """放一次 + 录一次 + 分析，返回结果字典"""
    print("   放 %.2f Hz / %.1f 秒（音量 %d）…" % (freq, secs, vol), flush=True)
    play_tone(freq, secs, vol)
    # 放音刚结束会有余响，等一小会儿再录，避免录到自己的尾巴
    time.sleep(0.4)

    print("   录基线（不放音）…", flush=True)
    base = to_mono(capture(secs))

    print("   放音同时录音…", flush=True)
    # ★★★ 2026-10-02 关键修正：必须【先起录音，再起放音】★★★
    #
    # 原来反过来（先 aplay，sleep 0.25，再 arecord），结果极不稳定：
    # 同一个音量连测 5 次，比值在 11.8 ~ 52.8 dB 之间乱跳（标准差 16.8 dB）。
    #
    # 查出来的原因（diag_timing.py 实测）：
    #   · arecord 从启动到真正出数据要 **142 ms**（打开设备 + 装 hw params）
    #   · 而 aplay 一启动就开始出声
    #   · 音只有 1 秒左右时，"先放 0.25 秒 + 录音启动 0.14 秒" = 0.39 秒已经过去，
    #     再叠上录音本身的开销，采集窗口经常只勉强搭住尾巴 —— 于是时好时坏
    #
    # 证据：把音放长到 4 秒、并且【先起 arecord 再起 aplay】，连测 5 次 5/5 成功。
    #
    # ⇒ 正确做法：先把 arecord 起起来（用子进程，它要一点时间才真正开始采），
    #   等它开始出数据了再起 aplay。这样采集窗口一定覆盖住。
    subprocess.run(["amixer", "-q", "-c", "0", "sset", "Playback", str(vol)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    tone_path = "/tmp/selftest_tone.wav"
    # ① 先起录音（起完等 0.25 秒让设备就绪）
    rec = subprocess.Popen(
        ["arecord", "-q", "-D", CAP_DEV, "-f", "S24_LE", "-c", "2",
         "-r", str(RATE), "-d", str(int(math.ceil(secs))), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    time.sleep(0.25)
    # ② 再起放音
    pp = subprocess.Popen(
        ["aplay", "-q", "-D", PLAY_DEV, tone_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # ③ 收录音结果
    try:
        raw = rec.communicate(timeout=secs + 15)[0] or b""
    except Exception:
        rec.kill()
        raw = b""
    try:
        pp.wait(timeout=secs + 10)
    except Exception:
        pp.kill()

    # 把 raw 转成样本（复用 capture 的那套符号扩展）
    a = array.array("i")
    a.frombytes(raw[:len(raw) & ~3])
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    play = to_mono(a)

    e_base = goertzel(base, freq)
    e_play = goertzel(play, freq)
    base_rms = rms(base)
    play_rms = rms(play)

    ratio = (e_play / e_base) if e_base > 0 else float("inf")
    ratio_db = 10 * math.log10(ratio) if ratio > 0 else -999.0

    return {
        "freq": freq,
        "base_rms_dbfs": round(dbfs(base_rms), 1),
        "play_rms_dbfs": round(dbfs(play_rms), 1),
        "base_tone": e_base,
        "play_tone": e_play,
        "ratio": ratio,
        "ratio_db": round(ratio_db, 1),
        "base_peak": max(abs(x) for x in base) if base else 0,
        "play_peak": max(abs(x) for x in play) if play else 0,
    }


def verdict(r):
    """根据比值给出判定

    ★ 依据文档教训：看 play/base 的【比值】，不是绝对能量。
      比值明显大于 1（比如 +6dB 以上）说明"放音时那个频率的能量确实涨了"，
      也就是麦克风真的听到了。
    """
    if r["ratio_db"] >= 12:
        return "优秀", "麦克风清晰听到纯音"
    if r["ratio_db"] >= 6:
        return "通过", "麦克风听到了（信噪比一般）"
    if r["ratio_db"] >= 3:
        return "勉强", "有一点点提升，可能是窜扰而非声学传导"
    return "失败", "没听到 —— 麦克风/模拟前端/采集通路有问题"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=float, default=DEFAULT_FREQ)
    ap.add_argument("--secs", type=float, default=1.2)
    ap.add_argument("--vol", type=int, default=33)
    ap.add_argument("--sweep", action="store_true",
                    help="扫多个频点（看整体频响）")
    # ★★★ 2026-10-02 改成"可选参数"形式：
    #     --json              -> 把 JSON 打到 stdout 最后一行（给服务/agent 解析）
    #     --json /tmp/x.json  -> 写到文件（原来的行为，保留）
    #   为什么：音频服务的 /selftest 要用 subprocess 调这个脚本并解析结果，
    #   如果 --json 必须带文件名，它就没法从 stdout 拿结果了。
    ap.add_argument("--json", nargs="?", const="__stdout__", default="",
                    help="不给值=打到 stdout；给路径=写文件")
    # ★ 静音锁开着的时候要放音，必须显式表态"用户已同意"
    ap.add_argument("--force", action="store_true",
                    help="静音锁开着也放音（表示用户已明确同意）")
    a = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("需要 root（要访问 /dev/snd）")

    # ★★★ 静音锁必须尊重（实测踩过：锁着的时候脚本照样放音了）
    #
    # 用户明确要求过："在他本人同意之前，不许发出任何声音"，
    # 靠的就是 /etc/zynq-silent 这个锁文件。
    # agent 的工具层（hw_acoustic_test）和音频服务的 /selftest 都检查了，
    # 但这个独立脚本漏了 —— 直接跑就出声。
    # ⇒ 补上。要放音就显式加 --force（表示"用户已同意"）。
    if os.path.exists(SILENT_FLAG) and not a.force:
        print("=" * 78)
        print(" ★ 静音模式开着（%s 存在）—— 声学自测要放音，拒绝执行" % SILENT_FLAG)
        print("=" * 78)
        print()
        print(" 三条路选一条：")
        print("   ① 解除静音:      sudo rm -f %s" % SILENT_FLAG)
        print("   ② 明确表示同意:  sudo python3 %s --force"
              % os.path.basename(__file__))
        print("   ③ 只录音不放音:  sudo python3 analyze_wav.py /tmp/x.raw")
        print()
        if a.json == "__stdout__":
            print("__JSON__" + json.dumps(
                {"ok": False, "verdict": "静音模式开着，拒绝放音",
                 "silent_locked": True}, ensure_ascii=False))
        return 3

    print("=" * 78)
    print(" 声学自测：放已知频率 -> 麦克风录回 -> 算比值")
    print("=" * 78)
    print(" ★ 判据用的是 play/base 的比值，不是绝对能量")
    print("   （文档记录：基线 100Hz 工频谐波能量极大，找最大能量会找错）")
    if os.path.exists(SILENT_FLAG):
        print(" ★ 静音锁开着，但给了 --force —— 按『用户已同意』处理")

    if a.sweep:
        freqs = [300, 500, 700, DEFAULT_FREQ, 1500, 2000, 3000, 4000]
    else:
        freqs = [a.freq]

    results = []
    for f in freqs:
        print("\n--- %.2f Hz ---" % f)
        try:
            r = one_test(f, a.secs, a.vol)
        except Exception as e:
            print("   ★ 失败: %s" % e)
            continue
        v, why = verdict(r)
        r["verdict"] = v
        r["why"] = why
        results.append(r)
        print("   基线 RMS %.1f dBFS / 峰值 %d" %
              (r["base_rms_dbfs"], r["base_peak"]))
        print("   放音 RMS %.1f dBFS / 峰值 %d" %
              (r["play_rms_dbfs"], r["play_peak"]))
        print("   ★ 目标频率能量比: %.1f dB  -> 【%s】%s"
              % (r["ratio_db"], v, why))

    print()
    print("=" * 78)
    print(" 汇总")
    print("=" * 78)
    if results:
        print(" %-10s %-12s %-12s %-10s %s" %
              ("频率(Hz)", "基线dBFS", "放音dBFS", "比值(dB)", "判定"))
        print(" " + "-" * 66)
        for r in results:
            print(" %-10.1f %-12.1f %-12.1f %-10.1f %s"
                  % (r["freq"], r["base_rms_dbfs"], r["play_rms_dbfs"],
                     r["ratio_db"], r["verdict"]))

        ok = [r for r in results if r["ratio_db"] >= 6]
        print()
        if len(ok) == len(results):
            print(" ★ 结论：全部频点都听到了 —— 声学通路【正常】")
        elif ok:
            print(" ★ 结论：%d/%d 个频点听到了 —— 部分正常（看上面的分布）"
                  % (len(ok), len(results)))
        else:
            print(" ★ 结论：一个都没听到 —— 声学通路有问题")
            print("   ⇒ 排查顺序：")
            print("     1. 麦克风采集本身有没有信号（先看安静时 RMS 是不是 -137）")
            print("     2. 喇叭有没有真的出声（人耳听一下）")
            print("     3. 音量是不是太小（--vol 调到 60 再试）")
            print("     4. 麦克风偏置/模拟前端")

    # ★ 统一的结果对象（服务/agent 要能直接拿去用）
    summary = {
        "ok": bool(results) and all(r["ratio_db"] >= 6 for r in results),
        "freq": results[0]["freq"] if len(results) == 1 else None,
        "secs": a.secs,
        "vol": a.vol,
        "verdict": ("全部频点都听到了" if results and
                    all(r["ratio_db"] >= 6 for r in results)
                    else ("%d/%d 个频点听到了"
                          % (len([r for r in results if r["ratio_db"] >= 6]),
                             len(results)) if results
                          else "一个都没听到")),
        "results": results,
    }

    if a.json == "__stdout__":
        # 打到 stdout 最后一行，方便调用方 split 最后一行解析
        print("\n__JSON__" + json.dumps(summary, ensure_ascii=False))
    elif a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        print("\n 结果已写 %s" % a.json)


if __name__ == "__main__":
    main()
