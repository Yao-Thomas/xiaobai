#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_wave_e2e_board.py —— ★ 板子侧：真机端到端推理验收

读取 PC 上生成的测试集（28×28 密度图 + 类别标签），
逐张送进 PL 加速器，比对类别。

★ 这才是完整的业务链：
    PC: dds_sim 生成 4096 点波形 → wdens 密度图 28×28（uint8）
    板: 读图 → int8(u8-128) → PL conv1→conv2→fc → argmax → 类别

和 verify_wave_onboard.py 的区别：
    那个验的是「参考输入 → 硬件 → 与参考输出逐点一致」（512/512 已过）
    这个验的是「预处理出来的图 → 硬件 → 类别对不对」

用法:
    sudo python3 verify_wave_e2e_board.py [文件]
    默认 /home/zynq/wave_e2e.bin
"""
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
CLASSES = ("sine", "square", "triangle", "sawtooth", "noise",
           "clipping", "signal_loss", "duty_abnormal")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/zynq/wave_e2e.bin"
    if not os.path.exists(path):
        print("找不到 %s" % path)
        return 1

    import cnn_linux as CL

    raw = open(path, "rb").read()
    if raw[:4] != b"WAVE":
        print("文件头不对（应该是 WAVE）")
        return 1
    n = struct.unpack("<I", raw[4:8])[0]
    print("=" * 74)
    print(" 波形识别 · 真机端到端验收（板子侧）")
    print("=" * 74)
    print(" 测试集: %s   %d 个样本" % (path, n))
    print(" 链路  : 28×28 密度图 → int8 → PL conv1→conv2→fc → 8 类")
    print()

    # 一次加载权重，反复推理
    c = CL.Cnn(verbose=False)
    w1, w2, wf = CL.load_wave_weights()
    c.w1.write(w1)
    c.w2.write(w2)
    c.wf.write(wf[:3200] + b"\x00" * (4032 - 3200))

    off = 8
    per = dict((i, [0, 0]) for i in range(8))
    hit = 0
    wrong = []
    for k in range(n):
        img = raw[off:off + 784]
        li = raw[off + 784]
        off += 785
        idx, name, lg = CL.wave_classify(img, c=c)
        per[li][1] += 1
        if idx == li:
            hit += 1
            per[li][0] += 1
        elif len(wrong) < 10:
            wrong.append((k, li, idx, lg))
    c.close()

    print(" 分类结果:")
    for i, lb in enumerate(CLASSES):
        h, t = per[i]
        bar = "█" * int(round(h * 20.0 / max(t, 1)))
        print("   %-15s %2d/%2d  %s" % (lb, h, t, bar))
    acc = hit / float(n) if n else 0
    print()
    print(" ★ 端到端准确率 %.1f%%（%d/%d）" % (acc * 100, hit, n))
    print("   交付包自己的测试集是 95.9%%，离线复刻 94.8%%")
    if wrong:
        print()
        print(" 误判（前 %d 个）:" % len(wrong))
        for k, li, idx, lg in wrong:
            print("   #%2d 真值 %-14s → 判成 %-14s logits=%s"
                  % (k, CLASSES[li], CLASSES[idx] if idx is not None else "?",
                     lg))
    print()
    print("=" * 74)
    ok = acc >= 0.80
    print(" 总体: %s" % ("★ 通过（≥80%）" if ok else "★ 偏低"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
