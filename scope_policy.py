#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_policy.py —— 示波器自动设置策略（板端驱动）

════════════════════════════════════════════════════════════════════
这是什么
════════════════════════════════════════════════════════════════════
AI 训练负责人（任务 E-①）训练的 RL 策略网络，交付物在
    ai_delivery/01_交付物/scope_policy_v4_quantized/
        weights.bin         11264 B  int8 权重
        model_spec.json     模型结构 + MFQ + 动作解码
        reference_in.bin    32 组 × 74 字节 int8
        reference_out.bin   32 组 × 37 字节 int8

它的作用：看当前波形和设置，给出三个建议 ——
    触发电平（16 档）/ 时基 DEC（16 档）/ 垂直增益（5 档）
RL 训出来是 11% → 92.2%（五种输入都能稳定显示 2~5 周期）。

════════════════════════════════════════════════════════════════════
★ 怎么接到硬件（关键：复用现成的 FC IP）
════════════════════════════════════════════════════════════════════
交付包 README 说「接上既有 IP 的 FC 通路即可推理」——
也就是用 CNN 那个 cnn_fc_q @0x43CE0000，不用新增 IP。

模型是 5 层 MLP，所以【调 5 次】FC：
    fc0   (74→64)  MFQ=374
    fc1   (64→64)  MFQ=333
    head0 (64→16)  MFQ=31     ← 触发电平 logits
    head1 (64→16)  MFQ=47     ← 时基 DEC logits
    head2 (64→5)   MFQ=45     ← 垂直增益 logits
三个 head 共享 fc1 的输出。
requant 沿用上一轮：out = sat((acc * MFQ) >> 16)

★ 注意：cnn_fc_q 和波形识别是【同一个 IP】，不能同时跑。
  两个功能要排队用。

════════════════════════════════════════════════════════════════════
板子上没有 numpy
════════════════════════════════════════════════════════════════════
他的 scope_env.py::_obs 用了 np.percentile / np.std / np.clip。
板子没 numpy，所以这里【纯 Python 复刻】：
    · percentile：numpy 默认的线性插值法（idx = p/100*(n-1)）
    · std：总体标准差（ddof=0，和 np.std 一致）
必须逐位对齐，否则 obs 量化后会差 1，logits 就跟着变。

用法（板子上 sudo）:
    sudo python3 scope_policy.py --verify      # 32 组参考验证（应 100%）
    sudo python3 scope_policy.py --demo        # 在内部 DDS 上跑一遍自动设置
"""
import argparse
import json
import math
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "ui"))

DELIV = "/home/zynq/scope_policy"
CAP_LEN = 4096
FS_BASE = 20_000_000.0          # DIV=5 时 20 MSPS
N_WAVE_BINS = 64
OBS_DIM = N_WAVE_BINS + 7 + 3   # 74

# ★ 动作档位表（和 scope_env.py 逐字一致）
TRIG_LEVELS = tuple(int(round(i * 255.0 / 15)) for i in range(16))
DEC_LEVELS = (1, 2, 3, 4, 6, 8, 11, 15, 21, 30, 43, 61, 86, 122, 173, 255)
VGAIN_LEVELS = (0.5, 0.7071067811865476, 1.0, 1.4142135623730951, 2.0)

# ★ weights.bin 的内存布局（交付包 README §4）
#   (层名, 文件偏移, IN, OUT, MFQ)
LAYERS = (
    ("fc0",   0x0000, 74, 64, 374),
    ("fc1",   0x1280, 64, 64, 333),
    ("head0", 0x2280, 64, 16,  31),   # 触发电平
    ("head1", 0x2680, 64, 16,  47),   # 时基 DEC
    ("head2", 0x2A80, 64,  5,  45),   # 垂直增益
)
W_BYTES = 11264


# ══════════════════════════════════════════════════════════════════
#  纯 Python 复刻 numpy 的几个统计函数（板子上没 numpy）
# ══════════════════════════════════════════════════════════════════
def np_percentile(sorted_vals, q):
    """复刻 numpy.percentile 的默认线性插值

    ★ 为什么不直接排序取第 k 个：numpy 默认是【线性插值】，
      比如 4096 个点的 5% 分位 = 第 204.75 个位置，
      要拿第 204 和第 205 个插值。直接取整会差 0.x，
      量化成 int8 之后就可能差 1，logits 跟着变。
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    idx = (q / 100.0) * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = idx - lo
    return float(sorted_vals[lo]) + (float(sorted_vals[hi]) - float(sorted_vals[lo])) * frac


def np_std(vals):
    """总体标准差（ddof=0，和 numpy 默认一致）"""
    n = len(vals)
    if n == 0:
        return 0.0
    m = sum(vals) / float(n)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / float(n))


def q_i8(x):
    """obs 浮点 -> int8

    交付包给的公式：i8 = round(clip(obs,-1,1) * 127)（round half to even）
    ★ Python 内置 round() 就是 half-to-even，正好对上，别用 int(x+0.5)
    """
    if x != x:                      # NaN
        return 0
    if x > 1.0:
        x = 1.0
    elif x < -1.0:
        x = -1.0
    return int(round(x * 127.0))


def compute_obs(samples, f_hz, wave_kind, trig_idx, dec_idx, vgain_idx):
    """复刻 scope_env.py::ScopeEnv._obs（纯 Python）

    samples  : 4096 个 uint8（示波器刚抓的一帧）
    f_hz     : 信号真实频率（Hz）；噪声填 0
    wave_kind: 波形类型（噪声时 K 记 0）
    *_idx    : 当前三个设置档位
    返回 74 个 float（值域 [-1,1]）
    """
    dec = DEC_LEVELS[dec_idx]

    # ── 64 段均值（reshape(64,64).mean(axis=1)）──
    step = CAP_LEN // N_WAVE_BINS          # 64
    wave = []
    for b in range(N_WAVE_BINS):
        seg = samples[b * step:(b + 1) * step]
        wave.append((sum(seg) / float(step) - 128.0) / 128.0)

    sv = sorted(samples)
    p5 = np_percentile(sv, 5.0)
    p95 = np_percentile(sv, 95.0)
    span = float(p95 - p5)
    occupy = span / 255.0
    mean = sum(samples) / float(len(samples))
    std = np_std(samples)

    # 周期数估计（噪声记 0）
    if wave_kind == 4:
        K = 0.0
    else:
        K = f_hz * CAP_LEN / (FS_BASE / float(dec))

    stats = [
        (mean - 128.0) / 128.0,                                         # 直流偏置
        min(max(std / 128.0, 0.0), 1.0) * 2.0 - 1.0,                    # 展宽
        (p5 - 128.0) / 128.0,                                           # 下包络
        (p95 - 128.0) / 128.0,                                          # 上包络
        (span / 128.0) - 1.0,                                           # 峰峰值
        2.0 * occupy - 1.0,                                             # 占屏
        min(max(math.log(max(K, 0.03), 2.0) / 6.0, -1.0), 1.0),         # 周期数（log2）
    ]
    settings = [
        TRIG_LEVELS[trig_idx] / 255.0 * 2.0 - 1.0,                      # 当前触发电平
        (dec_idx / 15.0) * 2.0 - 1.0,                                   # 当前时基档
        (vgain_idx / 4.0) * 2.0 - 1.0,                                  # 当前增益档
    ]
    return wave + stats + settings


# ══════════════════════════════════════════════════════════════════
#  策略网络驱动
# ══════════════════════════════════════════════════════════════════
class ScopePolicy(object):
    """用现成的 cnn_fc_q IP 跑这个 5 层 MLP"""

    def __init__(self, wpath=None, verbose=False):
        self.v = verbose
        self.wpath = wpath or os.path.join(DELIV, "weights.bin")
        if not os.path.exists(self.wpath):
            raise IOError("找不到权重 %s" % self.wpath)
        blob = open(self.wpath, "rb").read()
        if len(blob) != W_BYTES:
            raise ValueError("weights.bin 应该是 %d 字节，实际 %d"
                             % (W_BYTES, len(blob)))
        self.blob = blob
        self._cnn = None
        self._bufs = None

    # ---- 缓冲（复用 Cnn 的预留区分配）----
    def _setup(self):
        if self._bufs is not None:
            return
        import cnn_linux as CL
        self.CL = CL
        # ★ 这里只用 FC IP，不建整个 Cnn（省得占 conv 的缓冲）
        self.ip = CL.HlsIp(CL.FCQ_BASE, "cnn_fc_q")
        # 输入最大 74 -> 给 128；输出最大 64 -> 给 128
        self.bx = CL.DmaBuf(128, "sp_x")
        self.bx2 = CL.DmaBuf(128, "sp_x2")
        self.bw = CL.DmaBuf(W_BYTES, "sp_w")
        self.bo = CL.DmaBuf(128, "sp_o")
        self.bw.write(self.blob)
        self.bw.flush()
        self._bufs = True

    def _fc(self, xbuf, woff, outbuf, IN, OUT, mfq):
        """跑一次全连接（和 cnn_linux.Cnn.run_fc 一样的寄存器序列）"""
        ip = self.ip
        F_X, F_W, F_OUT = 0x10, 0x1c, 0x28
        F_IN, F_OUTN, F_MFQ = 0x34, 0x3c, 0x44
        ip.w64(F_X, self.bw.paddr + woff)
        # ★ 注意：权重指针要指向 偏移后的位置，不是 x 的
        ip.w64(F_W, self.bw.paddr + woff)
        ip.w64(F_OUT, outbuf.paddr)
        ip.w(F_IN, IN)
        ip.w(F_OUTN, OUT)
        ip.w(F_MFQ, mfq)
        ok, dt = ip.start_and_wait()
        if not ok:
            raise RuntimeError("FC 超时（%s）" % IN)
        return dt

    def _run_layer(self, xbuf, woff, outbuf, IN, OUT, mfq):
        ip = self.ip
        # x 指针
        ip.w64(0x10, xbuf.paddr)
        ip.w64(0x1c, self.bw.paddr + woff)
        ip.w64(0x28, outbuf.paddr)
        ip.w(0x34, IN)
        ip.w(0x3c, OUT)
        ip.w(0x44, mfq)
        ok, dt = ip.start_and_wait()
        if not ok:
            raise RuntimeError("FC 超时（IN=%d OUT=%d）" % (IN, OUT))
        return dt

    def infer(self, obs_float, want_logits=False):
        """obs（74 个 float）-> (trig_idx, dec_idx, vgain_idx) 及 logits"""
        self._setup()
        if len(obs_float) != OBS_DIM:
            raise ValueError("obs 应该是 %d 维，实际 %d"
                             % (OBS_DIM, len(obs_float)))
        # 量化
        q = bytes((q_i8(x) & 0xFF) for x in obs_float)
        self.bx.write(q)
        self.bx.flush()

        # fc0: obs(74) -> h0(64)
        self._run_layer(self.bx, 0x0000, self.bx2, 74, 64, 374)
        # fc1: h0(64) -> h1(64)      ★ 原地可能存在读写冲突，用两个缓冲轮换
        self._run_layer(self.bx2, 0x1280, self.bx, 64, 64, 333)
        # 三个 head 都读 bx（h1）
        res = {}
        for name, woff, IN, OUT, mfq in LAYERS[2:]:
            self._run_layer(self.bx, woff, self.bo, IN, OUT, mfq)
            self.bo.invalidate()
            res[name] = self.bo.as_i8()[:OUT]

        def amax(a):
            bi, bv = 0, a[0]
            for i, v in enumerate(a):
                if v > bv:
                    bi, bv = i, v
            return bi

        out = {
            "trig_idx": amax(res["head0"]),
            "dec_idx": amax(res["head1"]),
            "vgain_idx": amax(res["head2"]),
            "logits": res,
        }
        # 展开成连续的 37 字节（head0|head1|head2），方便和 reference 比
        flat = res["head0"] + res["head1"] + res["head2"]
        out["flat"] = flat
        res["head0"], res["head1"], res["head2"] = [], [], []
        return out

    def close(self):
        for b in (getattr(self, "bx", None), getattr(self, "bx2", None),
                  getattr(self, "bw", None), getattr(self, "bo", None)):
            if b is not None:
                try:
                    b.close()
                except Exception:
                    pass
        if getattr(self, "ip", None) is not None:
            try:
                self.ip.close()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
#  验收：32 组 reference 逐点比对
# ══════════════════════════════════════════════════════════════════
def verify(deliv=DELIV):
    print("=" * 74)
    print(" 示波器自动设置策略 · 板端验收")
    print("=" * 74)
    ri = os.path.join(deliv, "reference_in.bin")
    ro = os.path.join(deliv, "reference_out.bin")
    for p in (ri, ro, os.path.join(deliv, "weights.bin")):
        if not os.path.exists(p):
            print(" ★ 找不到 %s" % p)
            return 1
    rin = open(ri, "rb").read()
    rout = open(ro, "rb").read()
    n = len(rout) // 37
    print(" 参考数据: %d 组 × 74 字节输入 / 37 字节输出" % n)
    print()

    sp = ScopePolicy()
    try:
        bad = []
        same = 0
        for k in range(n):
            # ★ reference_in.bin 里就是 int8，直接拷（不要再做 obs→i8 换算）
            q = rin[k * 74:(k + 1) * 74]
            sp._setup()
            sp.bx.write(q)
            sp.bx.flush()
            sp._run_layer(sp.bx, 0x0000, sp.bx2, 74, 64, 374)
            sp._run_layer(sp.bx2, 0x1280, sp.bx, 64, 64, 333)
            flat = []
            for name, woff, IN, OUT, mfq in LAYERS[2:]:
                sp._run_layer(sp.bx, woff, sp.bo, IN, OUT, mfq)
                sp.bo.invalidate()
                flat += sp.bo.as_i8()[:OUT]
            want = list(struct.unpack_from("<37b", rout, k * 37))
            if flat == want:
                same += 1
                continue
            bad.append((k, flat, want))
        print(" 逐点比对:")
        print("   完全一致的组   : %d/%d" % (same, n))
        pts = 0
        for k in range(n):
            pass
        for k, got, want in bad[:6]:
            d = sum(1 for i in range(37) if got[i] != want[i])
            print("   ✗ 第 %2d 组: %d/37 不同" % (k, d))
            print("       实得 %s" % got)
            print("       期望 %s" % want)
        # 总点数
        good_pts = same * 37
        print()
        print(" ★ 总体: %s" % ("通过 —— 与 reference 逐位一致"
                               if same == n else
                               "★ 不一致（%d/%d 组对）" % (same, n)))
        return 0 if same == n else 1
    finally:
        sp.close()


def demo():
    """在内部 DDS 上跑一遍自动设置（验证闭环能转）"""
    print("=" * 74)
    print(" 示波器自动设置 · 内部 DDS 演示")
    print("=" * 74)
    import scope_capture as SC

    sp = ScopePolicy()
    try:
        for wave, name, f in ((0, "sine", 10000), (1, "square", 5000),
                              (2, "triangle", 20000), (3, "sawtooth", 3000)):
            r = SC.set_dds(wave, f, 100)
            if not r.get("ok"):
                print("  set_dds 失败: %s" % r.get("error"))
                continue
            cap = SC.capture_once(src=0, dec=1, timeout_ms=3000)
            if not cap.get("ok"):
                print("  采集失败: %s" % cap.get("error"))
                continue
            samples = list(cap["samples"])
            obs = compute_obs(samples, f, wave, 8, 5, 2)     # 用一套初始设置
            r = sp.infer(obs)
            print()
            print("  %-9s f=%6d Hz  实测峰峰=%d"
                  % (name, f, max(samples) - min(samples)))
            print("    建议 -> 触发电平 %3d (%2d/16)   时基 DEC %3d (%2d/16)   增益 %.2f (%d/5)"
                  % (TRIG_LEVELS[r["trig_idx"]], r["trig_idx"],
                     DEC_LEVELS[r["dec_idx"]], r["dec_idx"],
                     VGAIN_LEVELS[r["vgain_idx"]], r["vgain_idx"]))
        print()
        print("=" * 74)
        return 0
    finally:
        sp.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--deliv", default=DELIV)
    a = ap.parse_args()
    if a.verify:
        return verify(a.deliv)
    if a.demo:
        return demo()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
