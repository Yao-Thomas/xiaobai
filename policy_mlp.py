#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""policy_mlp.py —— ★ 通用的「多 head 量化 MLP」板端驱动

════════════════════════════════════════════════════════════════════
为什么写这个（一个驱动，两个模型）
════════════════════════════════════════════════════════════════════
AI 训练负责人交付了两个 RL 策略网络，结构【一模一样】：

    scope_policy_v4_quantized    74 维输入 → fc0(74→64) → fc1(64→64)
                                 → head0(64→16) head1(64→16) head2(64→5)
    eq_policy_quantized          16 维输入 → fc0(16→64) → fc1(64→64)
                                 → head0..head7(64→9 each)

两者的 requant 也完全一致（沿用上一轮 CNN 的方案）：
    out = sat((acc * MFQ) >> 16)       ← 算术右移 = floor，饱和到 [-128,127]
权重布局也一样（w[oc*IN + i] 行主序、128 字节对齐、无偏置）。

⇒ 所以只需要【一个】驱动，把层的表当参数传进来。

════════════════════════════════════════════════════════════════════
★ 复用现成的 IP，不新增硬件
════════════════════════════════════════════════════════════════════
交付包 README 说「接上既有 IP 的 FC 通路即可推理」——
就是用 CNN 那个 cnn_fc_q @0x43CE0000，一次调一层。

★ 注意：cnn_fc_q 和波形识别【共用同一个 IP】，
  agent 同时做波形识别和策略推理时要排队。

用法:
    from policy_mlp import PolicyNet, SPEC_SCOPE, SPEC_EQ
    net = PolicyNet(SPEC_SCOPE)              # 或 SPEC_EQ
    r = net.infer(q_bytes)                   # 输入 int8 字节
    print(r["heads"], r["argmax"], r["flat"])
    net.close()
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ══════════════════════════════════════════════════════════════════
#  两个模型的层表（来自各自 README 的内存布局 + model_spec.json）
# ══════════════════════════════════════════════════════════════════
# 每项: (层名, 文件偏移, IN, OUT, MFQ, 是否 head)
SPEC_SCOPE = {
    "name": "scope_policy_v4",
    "dir": "/home/zynq/scope_policy",
    "wbytes": 11264,
    "indim": 74,
    "outflat": 37,                      # 16+16+5
    "layers": [
        ("fc0",   0x0000, 74, 64, 374, False),
        ("fc1",   0x1280, 64, 64, 333, False),
        ("head0", 0x2280, 64, 16,  31, True),
        ("head1", 0x2680, 64, 16,  47, True),
        ("head2", 0x2A80, 64,  5,  45, True),
    ],
    "factor_names": ["trig_level", "dec", "vgain"],
}

SPEC_EQ = {
    "name": "eq_policy",
    "dir": "/home/zynq/eq_policy",
    "wbytes": 10240,
    "indim": 16,
    "outflat": 72,                      # 8 × 9
    "layers": [
        ("fc0",   0x0000, 16, 64, 343, False),
        ("fc1",   0x0400, 64, 64, 439, False),
        ("head0", 0x1400, 64,  9,  67, True),
        ("head1", 0x1680, 64,  9,  75, True),
        ("head2", 0x1900, 64,  9,  91, True),
        ("head3", 0x1B80, 64,  9,  82, True),
        ("head4", 0x1E00, 64,  9,  68, True),
        ("head5", 0x2080, 64,  9,  65, True),
        ("head6", 0x2300, 64,  9,  90, True),
        ("head7", 0x2580, 64,  9,  84, True),
    ],
    "factor_names": ["eq_band_%d" % i for i in range(8)],
}


def load_spec(deliv_dir):
    """从交付目录的 model_spec.json 读 MFQ 和布局，和内置表核对

    ★ 为什么要核对：MFQ 写错一个数字，结果就会整体偏，
      而且看起来"像是硬件坏了"。让脚本自己发现不一致更省事。
    """
    p = os.path.join(deliv_dir, "model_spec.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    mfq = (d.get("requant") or {}).get("MFQ_per_layer") or {}
    return {"mfq": mfq, "raw": d}


# ══════════════════════════════════════════════════════════════════
#  驱动
# ══════════════════════════════════════════════════════════════════
class PolicyNet(object):
    def __init__(self, spec, verbose=False):
        self.sp = spec
        self.v = verbose
        self.wpath = os.path.join(spec["dir"], "weights.bin")
        if not os.path.exists(self.wpath):
            raise IOError("找不到 %s" % self.wpath)
        blob = open(self.wpath, "rb").read()
        if len(blob) != spec["wbytes"]:
            raise ValueError("%s 应该是 %d 字节，实际 %d"
                             % (self.wpath, spec["wbytes"], len(blob)))
        self.blob = blob

        # 和交付的 model_spec.json 核对 MFQ（不一致就报出来）
        self.mfq_check = None
        md = load_spec(spec["dir"])
        if md and md["mfq"]:
            bad = []
            for name, off, IN, OUT, mfq, ish in spec["layers"]:
                got = md["mfq"].get(name)
                if got is not None and got != mfq:
                    bad.append("%s: 表里 %d / spec 里 %d" % (name, mfq, got))
            self.mfq_check = (not bad, bad)

        self._ready = False

    def _setup(self):
        if self._ready:
            return
        import cnn_linux as CL
        self.CL = CL
        self.ip = CL.HlsIp(CL.FCQ_BASE, "cnn_fc_q")
        # 输入最大 74 → 给 128；输出最大 64 → 给 128
        self.bx = CL.DmaBuf(128, self.sp["name"] + "_x")
        self.bx2 = CL.DmaBuf(128, self.sp["name"] + "_x2")
        self.bw = CL.DmaBuf(self.sp["wbytes"], self.sp["name"] + "_w")
        self.bo = CL.DmaBuf(128, self.sp["name"] + "_o")
        self.bw.write(self.blob)
        self.bw.flush()
        self._ready = True

    def _layer(self, xbuf, woff, outbuf, IN, OUT, mfq):
        ip = self.ip
        ip.w64(0x10, xbuf.paddr)              # x
        ip.w64(0x1c, self.bw.paddr + woff)    # w
        ip.w64(0x28, outbuf.paddr)            # out
        ip.w(0x34, IN)
        ip.w(0x3c, OUT)
        ip.w(0x44, mfq)
        ok, dt = ip.start_and_wait()
        if not ok:
            raise RuntimeError("FC 超时（IN=%d OUT=%d）" % (IN, OUT))
        return dt

    def infer(self, qbytes):
        """输入 int8 字节（长度 = spec['indim']）→ 各 head 的 logits

        返回 {"heads": {名字: [int8...]}, "argmax": {...}, "flat": [...]}
        """
        self._setup()
        if len(qbytes) != self.sp["indim"]:
            raise ValueError("输入应该是 %d 字节，实际 %d"
                             % (self.sp["indim"], len(qbytes)))
        self.bx.write(qbytes)
        self.bx.flush()

        # 前两层（共享）
        shared = [L for L in self.sp["layers"] if not L[5]]
        heads = [L for L in self.sp["layers"] if L[5]]

        # fc0: in -> 64（写 bx2）
        self._layer(self.bx, shared[0][1], self.bx2,
                    shared[0][2], shared[0][3], shared[0][4])
        cur, other = self.bx2, self.bx
        # 剩下的共享层（一般只有 fc1）
        for L in shared[1:]:
            self._layer(cur, L[1], other, L[2], L[3], L[4])
            cur, other = other, cur

        # 各 head 都读 cur
        res = {}
        flat = []
        for L in heads:
            self._layer(cur, L[1], self.bo, L[2], L[3], L[4])
            self.bo.invalidate()
            v = self.bo.as_i8()[:L[3]]
            res[L[0]] = v
            flat += v

        def amax(a):
            bi, bv = 0, a[0]
            for i, x in enumerate(a):
                if x > bv:
                    bi, bv = i, x
            return bi

        return {"heads": res,
                "argmax": dict((k, amax(v)) for k, v in res.items()),
                "flat": flat}

    def close(self):
        for a in ("bx", "bx2", "bw", "bo"):
            b = getattr(self, a, None)
            if b is not None:
                try:
                    b.close()
                except Exception:
                    pass
        ip = getattr(self, "ip", None)
        if ip is not None:
            try:
                ip.close()
            except Exception:
                pass
        self._ready = False


# ══════════════════════════════════════════════════════════════════
#  通用验收：reference_in → reference_out 逐点比对
# ══════════════════════════════════════════════════════════════════
def verify_reference(spec, verbose=True):
    """返回 {"ok", "groups", "total", "same_groups"}"""
    import struct
    d = spec["dir"]
    ri = os.path.join(d, "reference_in.bin")
    ro = os.path.join(d, "reference_out.bin")
    for p in (ri, ro):
        if not os.path.exists(p):
            raise IOError("找不到 %s" % p)
    rin = open(ri, "rb").read()
    rout = open(ro, "rb").read()
    indim, outdim = spec["indim"], spec["outflat"]
    n = len(rout) // outdim

    net = PolicyNet(spec, verbose=verbose)
    try:
        same = 0
        bad = []
        for k in range(n):
            q = rin[k * indim:(k + 1) * indim]
            # ★ reference_in.bin 里就是 int8，直接拷，不要再换算
            r = net.infer(q)
            want = list(struct.unpack_from("<%db" % outdim, rout, k * outdim))
            if r["flat"] == want:
                same += 1
            else:
                bad.append((k, r["flat"], want))
        return {"ok": same == n, "groups": n, "same_groups": same, "bad": bad}
    finally:
        net.close()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("which", nargs="?", default="scope",
                    choices=["scope", "eq", "both"])
    a = ap.parse_args()
    specs = [SPEC_SCOPE] if a.which == "scope" else (
        [SPEC_EQ] if a.which == "eq" else [SPEC_SCOPE, SPEC_EQ])

    allok = True
    for sp in specs:
        print("=" * 74)
        print(" %s  参考验证" % sp["name"])
        print("=" * 74)
        if not os.path.exists(os.path.join(sp["dir"], "weights.bin")):
            print(" ★ 交付物不在 %s，跳过" % sp["dir"])
            continue
        net = PolicyNet(sp)
        if net.mfq_check is not None:
            ok, bad = net.mfq_check
            print(" MFQ 与 model_spec.json 核对: %s"
                  % ("✓ 一致" if ok else "★ 不一致 -> %s" % bad))
        net.close()
        try:
            r = verify_reference(sp)
        except Exception as e:
            print(" ★ 出错: %s: %s" % (type(e).__name__, e))
            allok = False
            continue
        print(" 逐点比对: %d/%d 组完全一致" % (r["same_groups"], r["groups"]))
        for k, got, want in r["bad"][:4]:
            print("   ✗ 第 %d 组" % k)
            print("      实得 %s" % got)
            print("      期望 %s" % want)
        print(" ➜ %s" % ("★ 通过" if r["ok"] else "★ 不一致"))
        allok = allok and r["ok"]
        print()
    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过" if allok else "★ 有问题"))
    print("=" * 74)
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
