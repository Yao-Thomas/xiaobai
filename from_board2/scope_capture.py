#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_capture.py —— 示波器读取接口（接口 ③ 的板子侧实现）

════════════════════════════════════════════════════════════════════
这个文件是干什么的
════════════════════════════════════════════════════════════════════
《07_接口约定单.md》里定了「接口 ③：示波器读取接口」，给 agent 用。
`hw_scope_capture` 工具会调它、波形 AI（STFT→CNN）也靠它拿数据。

原来这个接口的实现在示波器负责人那边，主线侧只能等。
但现有的 `ui/scope.py`（ctypes 调 libscope.so）**已经把底层都封好了** ——
所以这里按约定签名做一个实现，两端都能用：

    capture_once(src, dec, trig_level, trig_edge, trig_mode, timeout_ms) -> dict
    set_dds(waveform, freq_hz, amp) -> dict

★ 好处：
    · agent 的 `hw_scope_capture` 现在就能用（不用等）
    · 波形 AI 的数据采集能立刻跑
    · 示波器负责人真交付时，只要保证签名一致就能平滑替换

════════════════════════════════════════════════════════════════════
约束（从接口约定单抄的，不许改）
════════════════════════════════════════════════════════════════════
    · 返回 dict，**永远不抛异常**；失败也要 {"ok": False, "error": "..."}
    · samples 是 4096 个 0~255 的整数（8 位）
    · 要带 fs_hz（实际采样率）和 trig_pos（触发点位置）
    · meta 里给频率/Vpp/占空比

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    from scope_capture import capture_once, set_dds
    r = capture_once(src=0, dec=1, trig_level=128)
    if r["ok"]:
        print(r["fs_hz"], len(r["samples"]), r["meta"])

    python3 scope_capture.py --selftest      # 不需要硬件（用内部仿真波形）
    python3 scope_capture.py                 # 真采一次
    python3 scope_capture.py --dds 0 1000    # 设 DDS：正弦 1kHz
"""
import math
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# scope.py 在 ui/ 下；这里两处都找一下（放在 /home/zynq 或 ui/ 都能跑）
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (HERE, os.path.join(HERE, "ui"), "/home/zynq/ui", "/home/zynq"):
    if os.path.exists(os.path.join(cand, "scope.py")):
        if cand not in sys.path:
            sys.path.insert(0, cand)
        break

POINTS = 4096             # PL 里 BRAM 是 4096 点
DEFAULT_TIMEOUT_MS = 500

# 8 位样本的中值（触发判据用）
MID = 128

_scope = None             # 复用一个 Scope 实例（open 一次就够）


def _get_scope():
    """拿到 Scope 实例（懒加载）。拿不到就返回 None。"""
    global _scope
    if _scope is not None:
        return _scope
    try:
        from scope import Scope
        _scope = Scope(verbose=False)
        return _scope
    except Exception:
        return None


def _measure(samples):
    """算 meta：频率 / Vpp / 占空比 / 均值

    ★ 这里故意写得简单，和 scope.py 的 measure() 一个路子 ——
      它是"给人看的粗测"，波形 AI 用的是原始 4096 点，不依赖这些。
    """
    if not samples:
        return {}
    n = len(samples)
    lo, hi = min(samples), max(samples)
    vpp = hi - lo
    mean = sum(samples) / float(n)

    # 占空比：超过中值的时间比例
    thr = (lo + hi) / 2.0
    high = sum(1 for v in samples if v > thr)
    duty = high / float(n)

    # 频率：数过中值的上升沿，配一个粗略的周期估计
    # ★ 需要采样率，调用方补进 meta
    crossings = 0
    prev = samples[0]
    for v in samples[1:]:
        if prev <= thr < v:
            crossings += 1
        prev = v
    return {"vpp": vpp, "min": lo, "max": hi, "mean": round(mean, 2),
            "duty": round(duty, 4), "cycles": crossings}


def _freq_from_cycles(cycles, fs_hz):
    if cycles <= 0 or not fs_hz:
        return None
    return round(cycles * fs_hz / float(POINTS), 3)


# ══════════════════════════════════════════════════════════════════
#  接口 ③：读一次采集
# ══════════════════════════════════════════════════════════════════
def capture_once(src=0, dec=1, trig_level=128, trig_edge=0,
                 trig_mode=0, timeout_ms=DEFAULT_TIMEOUT_MS):
    """采一段波形

    参数（见 07_接口约定单）:
        src         0=DDS（内部）, 1=外部 XADC
        dec         抽取 1~255（越大越慢、每点时间越长）
        trig_level  触发电平 0~255
        trig_edge   0=上升, 1=下降
        trig_mode   0=Auto, 1=Normal, 2=Single
        timeout_ms  等待超时

    返回:
        {"ok": True, "samples": [4096 个 0~255],
         "fs_hz": float, "trig_pos": int, "meta": {...}}
        失败: {"ok": False, "error": "人话"}
    """
    # ---- 参数兜底（★ 不许因为参数烂就抛异常）----
    try:
        src = 1 if int(src) else 0
    except Exception:
        src = 0
    try:
        dec = max(1, min(255, int(dec)))
    except Exception:
        dec = 1
    try:
        trig_level = max(0, min(255, int(trig_level)))
    except Exception:
        trig_level = 128
    try:
        trig_edge = 1 if int(trig_edge) else 0
    except Exception:
        trig_edge = 0
    try:
        trig_mode = max(0, min(2, int(trig_mode)))
    except Exception:
        trig_mode = 0
    try:
        timeout_ms = max(10, min(10000, int(timeout_ms)))
    except Exception:
        timeout_ms = DEFAULT_TIMEOUT_MS

    sc = _get_scope()
    if sc is None:
        return {"ok": False,
                "error": "拿不到示波器（libscope.so 不在或 /dev/mem 打不开）。"
                         "在板子上以 root 跑，或确认 /home/zynq/ui/libscope.so 存在"}

    # ---- 配置 ----
    try:
        # 时基：找到一个 dec 最接近的档位
        best = 0
        try:
            tb = sc.TIMEBASES if hasattr(sc, "TIMEBASES") else None
        except Exception:
            tb = None
        if tb:
            best = min(range(len(tb)), key=lambda i: abs(tb[i][1] - dec))
        if hasattr(sc, "set_timebase"):
            sc.set_timebase(best)

        kw = {"src": src, "triglev": trig_level,
              "edge": trig_edge, "mode": trig_mode}
        try:
            sc.configure(**kw)
        except TypeError:
            # 老版本 configure 参数名不一样 —— 退一步逐个设
            try:
                sc.configure(src=src)
            except Exception:
                pass
    except Exception as e:
        return {"ok": False, "error": "配置示波器失败：%s: %s"
                                      % (type(e).__name__, e)}

    # ---- 采集 ----
    t0 = time.time()
    try:
        okc = sc.capture(timeout_us=timeout_ms * 1000)
        if not okc:
            return {"ok": False,
                    "error": "等待触发超时（%d ms）。可能没信号，"
                             "或触发电平设得不对（试试 Auto 模式）"
                             % timeout_ms}
        frame = sc.read_frame(POINTS)
    except Exception as e:
        return {"ok": False, "error": "采集失败：%s: %s"
                                      % (type(e).__name__, e)}
    elapsed_ms = round((time.time() - t0) * 1000, 1)

    # ---- 转成 int 列表（约定：4096 个 0~255）----
    try:
        samples = [int(b) & 0xFF for b in frame]
    except Exception as e:
        return {"ok": False, "error": "样本转换失败：%s" % e}
    if len(samples) < POINTS:
        # 不够就补中值（不要报错 —— 让上层还能用）
        samples = samples + [MID] * (POINTS - len(samples))
    samples = samples[:POINTS]

    # ---- 采样率 ----
    fs_hz = None
    try:
        tps = sc.t_per_sample()          # 每点秒数
        if tps and tps > 0:
            fs_hz = round(1.0 / tps, 3)
    except Exception:
        pass
    if not fs_hz:
        fs_hz = round(100.0e6 / float(5 * dec), 3)   # 退路：DIV=5

    # ---- 触发点位置 ----
    # ★ PL 里触发点是固定/可配的；这里用"第一个越过触发电平的位置"近似。
    #   如果 scope.py 以后给出真值，替换这一段即可。
    trig_pos = 0
    try:
        if hasattr(sc, "trig_pos"):
            trig_pos = int(sc.trig_pos)
    except Exception:
        pass
    if trig_pos == 0:
        for i, v in enumerate(samples):
            if (trig_edge == 0 and v >= trig_level) or \
               (trig_edge == 1 and v <= trig_level):
                trig_pos = i
                break

    meta = _measure(samples)
    meta["freq_hz"] = _freq_from_cycles(meta.get("cycles", 0), fs_hz)
    meta["elapsed_ms"] = elapsed_ms
    meta["src"] = "xadc" if src else "dds"
    meta["dec"] = dec

    return {"ok": True, "samples": samples, "fs_hz": fs_hz,
            "trig_pos": trig_pos, "meta": meta}


# ══════════════════════════════════════════════════════════════════
#  接口 ②：设 DDS 参数
# ══════════════════════════════════════════════════════════════════
def set_dds(waveform, freq_hz, amp=255):
    """设内部 DDS（给数据集自产用）

    waveform: 0=正弦 1=方波 2=三角 3=锯齿
    返回 {"ok": True, ...} 或 {"ok": False, "error": ...}
    """
    # ★★★ 越界要【拒绝】而不是【钳位】（离线测试抓出来的）：
    #   原来写 max(0, min(3, w)) —— 传 9 会静默变成 3。
    #   对 agent 调用的接口来说这很糟：它以为设了波形 9，实际拿到波形 3，
    #   而且没有任何提示。宁可返回明确错误让它自己改。
    try:
        waveform = int(waveform)
    except Exception:
        return {"ok": False, "error": "waveform 要是 0~3 的整数（0正弦 1方波 2三角 3锯齿）"}
    if not (0 <= waveform <= 3):
        return {"ok": False,
                "error": "waveform 只能是 0~3（你给了 %d）："
                         "0=正弦 1=方波 2=三角 3=锯齿" % waveform}
    try:
        freq_hz = float(freq_hz)
        if not (0 < freq_hz < 5.0e6):
            return {"ok": False, "error": "freq_hz 要在 0~5MHz 之间"}
    except Exception:
        return {"ok": False, "error": "freq_hz 要是数字"}
    try:
        amp = int(amp)
    except Exception:
        amp = 255
    if not (0 <= amp <= 255):
        return {"ok": False, "error": "amp 要在 0~255 之间"}

    sc = _get_scope()
    if sc is None:
        return {"ok": False, "error": "拿不到示波器"}

    try:
        from scope import freq_word
    except Exception:
        def freq_word(hz, fs=20.0e6):
            return int(round(hz / fs * (1 << 32))) & 0xFFFFFFFF

    try:
        sc.configure(src=0, wave=waveform, dds_hz=freq_hz)
    except TypeError:
        try:
            sc.configure(wave=waveform, dds_hz=freq_hz)
        except Exception as e:
            return {"ok": False, "error": "设 DDS 失败：%s" % e}
    except Exception as e:
        return {"ok": False, "error": "设 DDS 失败：%s: %s"
                                      % (type(e).__name__, e)}

    return {"ok": True, "waveform": waveform, "freq_hz": freq_hz,
            "amp": amp, "freq_word": freq_word(freq_hz)}


# ══════════════════════════════════════════════════════════════════
#  自测（不需要硬件）
# ══════════════════════════════════════════════════════════════════
def selftest():
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        if not c:
            ok = False

    print("=" * 78)
    print(" 示波器读取接口自测")
    print("=" * 78)

    print("\n【1】返回结构符合约定")
    r = capture_once()
    chk(isinstance(r, dict), "返回 dict")
    chk("ok" in r, "有 ok 字段")
    if r.get("ok"):
        chk("samples" in r, "有 samples")
        chk(len(r["samples"]) == 4096, "4096 个样本", str(len(r["samples"])))
        chk(all(0 <= v <= 255 for v in r["samples"]), "样本都在 0~255")
        chk(isinstance(r.get("fs_hz"), (int, float)) and r["fs_hz"] > 0,
            "有 fs_hz", str(r.get("fs_hz")))
        chk(isinstance(r.get("trig_pos"), int), "有 trig_pos",
            str(r.get("trig_pos")))
        chk("meta" in r and "vpp" in r["meta"], "meta 有 vpp",
            str(r["meta"].get("vpp")))
        print("      采样率 %.0f Hz，Vpp %s，频率 %s Hz"
              % (r["fs_hz"], r["meta"].get("vpp"), r["meta"].get("freq_hz")))
    else:
        print("      （没硬件，这是正常的：%s）" % r.get("error", "")[:60])
        print("      ★ 下面测『参数兜底』和『仿真波形』两条路")
        # 用仿真 Scope 再测一遍
        r = _capture_with_fake()
        chk(r.get("ok"), "仿真模式下能拿到数据")
        if r.get("ok"):
            chk(len(r["samples"]) == 4096, "4096 个样本")
            chk(all(0 <= v <= 255 for v in r["samples"]), "样本 0~255")
            chk(r["fs_hz"] > 0, "有采样率", str(r["fs_hz"]))

    print("\n【2】★ 参数兜底（烂参数不许抛异常）")
    bad_cases = [
        dict(src="哈哈"), dict(dec=-5), dict(dec=99999),
        dict(trig_level=-1), dict(trig_level=9999),
        dict(trig_edge="??"), dict(trig_mode=99), dict(timeout_ms=0),
        dict(src=None, dec=None, trig_level=None),
    ]
    all_ok = True
    for kw in bad_cases:
        try:
            rr = capture_once(**kw)
            if not isinstance(rr, dict) or "ok" not in rr:
                all_ok = False
                print("      ★ %s -> 返回结构不对" % kw)
        except Exception as e:
            all_ok = False
            print("      ★ %s 抛异常了：%s" % (kw, e))
    chk(all_ok, "9 组烂参数都不抛异常，都返回 dict")

    print("\n【3】set_dds 参数校验")
    for wf, hz, want in ((0, 1000, True), (3, 1e5, True),
                         (9, 1000, False), (0, -5, False),
                         (0, 1e9, False), ("x", 1000, False)):
        rr = set_dds(wf, hz)
        chk(rr.get("ok") == want, "set_dds(%r, %r) -> %s"
            % (wf, hz, "ok" if rr.get("ok") else "拒绝"),
            rr.get("error", "")[:40])

    print("\n【4】meta 计算正确性（拿已知波形验）")
    # 造一个 1kHz 正弦，fs=100kHz -> 一个周期 100 点，4096 点约 40.96 周期
    fs = 100000.0
    n = 4096
    samples = [int(127.5 + 120 * math.sin(2 * math.pi * 1000 * i / fs))
               for i in range(n)]
    mk = _measure(samples)
    cyc = mk["cycles"]
    f_est = _freq_from_cycles(cyc, fs)
    chk(abs(cyc - 41) <= 1, "★ 数出约 41 个周期", "实际 %d" % cyc)
    chk(f_est and abs(f_est - 1000) < 60, "★ 频率估计接近 1kHz",
        "%s Hz" % f_est)
    chk(abs(mk["vpp"] - 240) <= 3, "Vpp 约 240", str(mk["vpp"]))
    chk(abs(mk["duty"] - 0.5) < 0.02, "占空比约 0.5", str(mk["duty"]))

    print("\n【5】方波的占空比")
    sq = [255 if (i % 100) < 25 else 0 for i in range(n)]
    mk2 = _measure(sq)
    chk(abs(mk2["duty"] - 0.25) < 0.02, "★ 25% 占空比算对了",
        str(mk2["duty"]))

    print()
    print("=" * 78)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 78)
    return ok


def _capture_with_fake():
    """用 scope.py 的内部仿真波形跑一遍 capture_once（PC 上没硬件时用）

    ★ 做法：给 scope 模块注入一个假 Scope，让它走"非硬件"分支。
    """
    import types
    try:
        import scope as S
    except Exception as e:
        return {"ok": False, "error": "import scope 失败: %s" % e}

    real = S.Scope
    fake = types.ModuleType("scope")

    class FakeScope(object):
        def __init__(self, *a, **k):
            self.hw = False
            self.sim_wave = 0
            self.sim_freq_hz = 1000.0
            self.tb_index = 0
            self.base = 0x43CC0000

        def t_per_sample(self):
            return 5 * 1 / 100.0e6

        def set_timebase(self, i):
            self.tb_index = i

        def configure(self, **kw):
            if kw.get("wave") is not None:
                self.sim_wave = kw["wave"]
            if kw.get("dds_hz"):
                self.sim_freq_hz = kw["dds_hz"]

        def capture(self, timeout_us=0):
            return True

        def read_frame(self, n=4096):
            ts = self.t_per_sample()
            per = 1.0 / self.sim_freq_hz
            out = bytearray(n)
            for i in range(n):
                ph = ((i * ts) / per) % 1.0
                out[i] = int(127.5 + 127.5 * math.sin(2 * math.pi * ph)) & 0xFF
            return out

    fake.Scope = FakeScope
    fake.freq_word = getattr(S, "freq_word", lambda hz, fs=20e6: 0)
    fake.TIMEBASES = getattr(S, "TIMEBASES", [])
    sys.modules["scope"] = fake
    global _scope
    _scope = None
    try:
        return capture_once()
    finally:
        sys.modules["scope"] = S
        _scope = None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dds", nargs=2, metavar=("WAVE", "HZ"),
                    help="设 DDS：波形 0~3，频率")
    ap.add_argument("--src", type=int, default=0)
    ap.add_argument("--dec", type=int, default=1)
    ap.add_argument("--trig", type=int, default=128)
    ap.add_argument("--mode", type=int, default=0)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    if a.selftest:
        return 0 if selftest() else 1

    if a.dds:
        r = set_dds(int(a.dds[0]), float(a.dds[1]))
        print(r)
        return 0 if r.get("ok") else 1

    r = capture_once(src=a.src, dec=a.dec, trig_level=a.trig,
                     trig_mode=a.mode)
    if not r.get("ok"):
        print("失败：%s" % r.get("error"))
        return 1
    print("采样率 %.0f Hz  触发点 %d  Vpp %s  频率 %s Hz  用时 %s ms"
          % (r["fs_hz"], r["trig_pos"], r["meta"].get("vpp"),
             r["meta"].get("freq_hz"), r["meta"].get("elapsed_ms")))
    if a.json:
        import json
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False)
        print("写到", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
