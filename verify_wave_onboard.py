#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_wave_onboard.py —— ★ 波形模型上板验收（板子上跑）

════════════════════════════════════════════════════════════════════
这是《quantized_model/README.md §3》指定的唯一可靠验证做法
════════════════════════════════════════════════════════════════════
    对第 k 个输入跑一遍硬件 → 读回 8 字节 logits
    与 reference_out.bin[k*8:(k+1)*8] 逐点比对 → 应 100% 相同

期望输出形如上一轮的 [CNN OK] 8/8 点一致。

════════════════════════════════════════════════════════════════════
四道关（★ 一道不过就别往下走）
════════════════════════════════════════════════════════════════════
  ① 文件都在、大小对、md5 对（★ 权重错了后面全是白搭）
  ② CNN IP 能读到 VERSION（PL 真的加载了）
  ③ 64 组 reference 逐点比对 → 期望 512/512
  ④ 类别 argmax 和标签对得上（准确性旁证）

用法（板子上）:
    sudo python3 verify_wave_onboard.py
    sudo python3 verify_wave_onboard.py --n 8      # 只跑前 8 组（快）
"""
import argparse
import hashlib
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
W_DIR = "/home/zynq"
WEIGHTS = os.path.join(W_DIR, "wave_weights.bin")
REF_IN = os.path.join(W_DIR, "wave_reference_in.bin")
REF_OUT = os.path.join(W_DIR, "wave_reference_out.bin")
SPEC = os.path.join(W_DIR, "wave_model_spec.json")

# ★ 交付包里的 md5（从 D:\ubuntu_iso\wave_model\ 算出来的，防止传坏）
MD5 = {
    "wave_weights.bin": "27890abfb906ca32be242a7872b92078",
    "wave_reference_in.bin": "4ac75fc2386959b1fad278652608e6c0",
    "wave_reference_out.bin": "1e0cff3023d9bc7196686ef6941e4aa2",
}

ok_all = True


def chk(cond, msg, detail=""):
    global ok_all
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok_all = False
    return cond


def md5f(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="只跑前 N 组（0=全部 64）")
    ap.add_argument("--weights", default=WEIGHTS)
    ap.add_argument("--ref-in", default=REF_IN)
    ap.add_argument("--ref-out", default=REF_OUT)
    a = ap.parse_args()

    print("=" * 74)
    print(" 波形模型 · 上板验收")
    print("=" * 74)
    print(" 时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print()

    # ══════════ ① 文件 ══════════
    print("【1】文件")
    for p, want in ((a.weights, 4480), (a.ref_in, 50176), (a.ref_out, 512)):
        if not chk(os.path.exists(p), "%s 在" % os.path.basename(p), p):
            print("\n★ 文件不全，先跑部署脚本")
            return 1
        sz = os.path.getsize(p)
        chk(sz == want, "%s 大小 %d" % (os.path.basename(p), want),
            "实际 %d" % sz)
    got = md5f(a.weights)
    exp = MD5["wave_weights.bin"]
    chk(got == exp, "★ weights.bin md5 与交付包一致（防传坏）",
        got[:16] + "…" if got == exp else "实得 %s / 期望 %s" % (got[:16], exp[:16]))
    got_in = md5f(a.ref_in)
    chk(got_in == MD5["wave_reference_in.bin"], "★ reference_in.bin md5 一致",
        got_in[:16] + "…" if got_in == MD5["wave_reference_in.bin"]
        else "实得 %s" % got_in[:16])
    got_out = md5f(a.ref_out)
    chk(got_out == MD5["wave_reference_out.bin"], "★ reference_out.bin md5 一致",
        got_out[:16] + "…" if got_out == MD5["wave_reference_out.bin"]
        else "实得 %s" % got_out[:16])

    with open(a.weights, "rb") as f:
        wb = f.read()
    with open(a.ref_in, "rb") as f:
        rin = f.read()
    with open(a.ref_out, "rb") as f:
        rout = f.read()
    n_all = len(rout) // 8
    print("   权重: conv1=%d B  conv2=%d B  fc=%d B"
          % (72, 1152, 3200))
    print("   reference: %d 组" % n_all)
    print()

    # ══════════ ② CNN IP ══════════
    print("【2】CNN IP 在线")
    sys.path.insert(0, W_DIR)
    try:
        import cnn_linux as CL
    except Exception as e:
        chk(False, "import cnn_linux", "%s: %s" % (type(e).__name__, e))
        return 1
    chk(CL.MFQ_C1 == 201 and CL.MFQ_C2 == 371 and CL.MFQ_FC == 1390,
        "★ 逐层 MFQ = 201/371/1390",
        "%d/%d/%d" % (CL.MFQ_C1, CL.MFQ_C2, CL.MFQ_FC))
    chk(CL.FCO_WAVE == 8, "输出 8 类", str(CL.FCO_WAVE))
    chk(hasattr(CL, "verify_wave_reference"),
        "有 verify_wave_reference()")
    try:
        import mmap
        import struct
        for base, nm in ((0x43CD0000, "cnn_conv_pool"), (0x43CE0000, "cnn_fc")):
            fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
            m = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ,
                          offset=base)
            # ★ 读 0x00 ap_ctrl —— idle 时应该是 0x04（ap_idle 置位）
            #   我第一次读 0x34，那是 IH（输入高度），idle 时当然是 0，
            #   于是误判成"IP 不在线"。偏移一定要按 2026.1 的表来。
            ap = struct.unpack_from("<I", m, 0x00)[0]
            m.close()
            os.close(fd)
            chk(ap & 0x4 == 0x4, "%s ap_ctrl idle(0x04)" % nm, "0x%08X" % ap)
    except Exception as e:
        chk(False, "读 CNN 寄存器", "%s: %s" % (type(e).__name__, e))
    print()

    # ══════════ ③ 逐点比对 ══════════
    n = a.n if a.n else n_all
    print("【3】reference 逐点比对（%d 组 × 8 点 = %d 点）"
          % (n, n * 8))
    print("   ★ 这一关就是 README 指定的唯一可靠做法")
    t0 = time.time()
    try:
        c = CL.Cnn(verbose=False)
        c.w1.write(wb[0x0000:0x0000 + 72])
        c.w2.write(wb[0x0080:0x0080 + 1152])
        c.wf.write(wb[0x0500:0x0500 + 3200] + b"\x00" * (4032 - 3200))
        c.w1.flush()
        c.w2.flush()
        c.wf.flush()

        same = 0
        gok = 0
        bad = []
        argmax_ok = 0
        labels = None
        if os.path.exists(SPEC):
            try:
                sp = json.loads(open(SPEC, encoding="utf-8").read())
                labels = sp["reference"]["labels"]
            except Exception:
                pass

        for k in range(n):
            # ★★★ reference_in.bin 里【已经就是 int8】，直接拷，不要再 -128 ★★★
            #   README §3：「拷进加速器输入缓冲」；§9：「不要送原始 0~255」
            #   （我第一次写成了 (b-128)&0xFF，减了两次，512 点只对 3 点）
            c.img.write(rin[k * 784:(k + 1) * 784])
            c.img.flush()
            c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
            c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2,
                      mfq=CL.MFQ_C2)
            c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, CL.FCO_WAVE, mfq=CL.MFQ_FC)
            c.lg.invalidate()
            got8 = c.lg.read(8)
            want8 = rout[k * 8:(k + 1) * 8]
            if got8 == want8:
                gok += 1
            elif len(bad) < 5:
                bad.append((k, list(got8), list(want8)))
            for i in range(8):
                if got8[i] == want8[i]:
                    same += 1
            if labels and k < len(labels):
                lg = [x - 256 if x >= 128 else x for x in got8]
                top = CL.WAVE_CLASSES[max(range(8), key=lambda i: lg[i])]
                if top == labels[k]:
                    argmax_ok += 1
        c.close()
        dt = time.time() - t0

        print("   [CNN OK] %d/%d 点一致" % (same, n * 8))
        for k, g, w in bad:
            print("      ✗ 第 %d 组: 实得 %s / 期望 %s" % (k, g, w))
        chk(same == n * 8, "★ 全部 %d 点一致" % (n * 8),
            "%d/%d" % (same, n * 8))
        chk(gok == n, "%d 组全对" % n, "%d/%d" % (gok, n))
        if labels:
            chk(argmax_ok >= int(n * 0.9),
                "argmax 类别和标签对得上",
                "%d/%d（旁证，不必 100%%）" % (argmax_ok, n))
        print("   耗时 %.2f 秒（%.1f ms/组）" % (dt, dt * 1000 / max(1, n)))
    except Exception as e:
        chk(False, "跑硬件", "%s: %s" % (type(e).__name__, e))
        import traceback
        traceback.print_exc()
    print()

    # ══════════ ④ 速度 ══════════
    print("【4】速度（顺手给个数字）")
    if n > 0:
        print("   单组约 %.1f ms（含 flush/invalidate 开销）"
              % (dt * 1000 / max(1, n)))
        print("   ★ 对照：CPU 纯 Python 复刻一组约 800 ms —— 快约 %.0f 倍"
              % (800.0 / max(dt * 1000 / max(1, n), 0.001)))
    print()

    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过 —— 波形模型上板成功" if ok_all
                        else "★ 有问题，看上面 ✗"))
    print("=" * 74)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
