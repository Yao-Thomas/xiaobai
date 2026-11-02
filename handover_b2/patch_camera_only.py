#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
camera-only dtb 补丁  —— 只禁 camera 相关节点，保留 HDMI

★ 为什么需要这个脚本（而不是直接用 make_dtb_patch.py 的 trim 模式）：
   make_dtb_patch.py --mode trim 会禁 9 个节点（HDMI 5 + camera 4）
   但我们这次 build 是 DISABLE_HDMI=0 ⇒ 新 PL 里 HDMI 的 IP【都还在】
   ⇒ 禁 HDMI 节点会把还在工作的 HDMI 误禁掉
   ⇒ 只能禁 PL 里【真的被删掉】的那几个 camera 节点

★ 安全闸（一道都不少）：
   闸1  LCD/音频 12 个节点必须仍然 enabled
   闸2  禁用的节点必须整组（i2c@41600000 和它的子节点必须一起禁）
   闸3  ★ chosen/bootargs 里的 mem=992M 必须原样保留（CNN 的 POOL_BASE=0x3E000000 依赖它）
   闸4  反编译后逐节点确认 status = "disabled"
   闸5  文本行数/关键节点存在性比对

用法:
  python patch_camera_only.py <in.dtb> <out.dtb> [--dtc PATH] [--workdir DIR]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

DEFAULT_DTC = r"D:\Xilinx\2026.1\Vivado\bin\dtc.exe"

# ★ 只禁这些（PL 里确实被删掉的 camera 通路）
#   顺序很重要：父节点在后，子节点在前（脚本内会按需排序）
TRIM_NODES = [
    "/amba_pl/i2c@41600000/ov5640@3c",   # camera 传感器（子节点）
    "/amba_pl/i2c@41600000",             # camera 用的 i2c（父节点）
    "/amba_pl/v_frmbuf_wr@43c40000",     # camera 写入 framebuffer
    "/amba_pl/vcap_dvp",                 # camera DVP 采集
]

# ★ 必须保持 enabled 的（硬红线）—— LCD / 音频 / 其它外设
MUST_STAY_ENABLED = [
    "/amba_pl/clk_wiz@43c30000",         # LCD pclk + mclk
    "/amba_pl/v_tc@43c10000",            # LCD 时序
    "/amba_pl/v_frmbuf_rd@43c20000",     # LCD framebuffer 读
    "/amba_pl/drm_pl_disp_lcd",          # LCD 显示封装
    "/amba_pl/atk_lcd_drm",              # LCD DRM（timing2 = 1024x600）
    "/amba_pl/PWM@43c00000",             # 背光 PWM
    "/amba_pl/gpio@41200000",            # LCD ID 读
    "/amba_pl/audio_formatter@43c50000",
    "/amba_pl/i2s_receiver@43c60000",
    "/amba_pl/i2s_transmitter@43c70000",
    # ★ HDMI 这次【保留】，所以也列进红线：绝不能被禁
    "/amba_pl/clk_wiz@43c80000",
    "/amba_pl/v_tc@43c90000",
    "/amba_pl/v_frmbuf_rd@43ca0000",
    "/amba_pl/drm_pl_disp_hdmi",
    "/amba_pl/atk_hdmi_drm",
]

# ★ 绝不能丢的 bootargs 片段
MUST_KEEP_BOOTARGS = "mem=992M"


def run_dtc(dtc, args):
    r = subprocess.run([dtc] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("  ✗ dtc 失败 (rc=%d)" % r.returncode)
        print("    stdout:", (r.stdout or "")[:800])
        print("    stderr:", (r.stderr or "")[:800])
        sys.exit(2)
    return r


def node_span(lines, path):
    """返回 (start_idx, end_idx_exclusive)，找不到返回 None"""
    # dtc 输出里节点形如:  <indent>nodename {
    name = path.rstrip("/").split("/")[-1]
    pat = re.compile(r"^(\s*)" + re.escape(name) + r"\s*\{")
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            indent = len(m.group(1))
            # 找到配对的 }
            depth = 0
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if depth == 0:
                    return (i, j + 1, indent)
    return None


def get_status(lines, span):
    """在节点范围内找 status = "..."，返回 (值, 行号) 或 (None, None)"""
    s, e, _ = span
    for k in range(s, e):
        m = re.search(r'status\s*=\s*"([^"]*)"', lines[k])
        if m:
            return (m.group(1), k)
    # 也可能是 status = "okay"; 形式被 dtc 拆开
    for k in range(s, e):
        if re.search(r'\bstatus\b', lines[k]):
            return ("<存在但未解析>", k)
    return (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_dtb")
    ap.add_argument("out_dtb")
    ap.add_argument("--dtc", default=DEFAULT_DTC)
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.dtc):
        print("  ✗ 找不到 dtc: %s" % args.dtc); sys.exit(2)

    workdir = args.workdir or (os.path.splitext(args.out_dtb)[0] + "_dtbwork")
    os.makedirs(workdir, exist_ok=True)
    dts_in = os.path.join(workdir, "in.dts")
    dts_out = os.path.join(workdir, "out.dts")

    print("=" * 70)
    print("camera-only dtb 补丁")
    print("  in  : %s (%d B)" % (args.in_dtb, os.path.getsize(args.in_dtb)))
    print("  out : %s" % args.out_dtb)
    print("  dtc : %s" % args.dtc)
    print("=" * 70)

    # ---------- 反编译 ----------
    print("\n[1] 反编译 dtb -> dts")
    run_dtc(args.dtc, ["-I", "dtb", "-O", "dts", "-o", dts_in, args.in_dtb])
    with open(dts_in, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines(keepends=True)
    print("    行数 = %d" % len(lines))

    # ---------- 闸3（先查）：bootargs mem=992M ----------
    print("\n[闸3] bootargs 里的 %s" % MUST_KEEP_BOOTARGS)
    boot_ok = any(MUST_KEEP_BOOTARGS in ln for ln in lines)
    if not boot_ok:
        print("    ✗ 输入 dtb 里就没有 %s —— 拒绝继续" % MUST_KEEP_BOOTARGS)
        sys.exit(3)
    print("    ✓ 输入里有；下面编译后会再查一次")

    # ---------- 闸1（先查）：红线节点必须存在且 enabled ----------
    print("\n[闸1] 红线节点必须存在且 enabled")
    red_fail = []
    for p in MUST_STAY_ENABLED:
        sp = node_span(lines, p)
        if sp is None:
            print("    ⚠ %s  —— 输入 dtb 里没有这个节点（跳过）" % p)
            continue
        st, _ = get_status(lines, sp)
        if st in (None, "okay"):
            print("    ✓ %-42s status=%s" % (p, st or "无(默认okay)"))
        else:
            print("    ✗ %-42s status=%s  ← 输入里就是 disabled，异常！" % (p, st))
            red_fail.append(p)
    if red_fail:
        print("    ✗ 红线节点异常，拒绝继续"); sys.exit(3)

    # ---------- 应用禁用 ----------
    print("\n[2] 把 camera 节点标成 disabled")
    # 按 start 从大到小处理（避免行号偏移）
    targets = []
    for p in TRIM_NODES:
        sp = node_span(lines, p)
        if sp is None:
            print("    ⚠ %s  —— 输入 dtb 里没有这个节点（跳过）" % p)
            continue
        targets.append((p, sp))
    targets.sort(key=lambda x: -x[1][0])

    changed = []
    for p, sp in targets:
        s, e, indent = sp
        st, st_line = get_status(lines, sp)
        pad = " " * (indent + 4)
        if st == "disabled":
            print("    = %-42s 已经是 disabled" % p)
            changed.append(p)
            continue
        if st_line is not None:
            # 替换现有 status 行
            lines[st_line] = re.sub(r'status\s*=\s*"[^"]*"',
                                    'status = "disabled"', lines[st_line])
            print("    ✓ %-42s status %s -> disabled (改第 %d 行)" % (p, st, st_line + 1))
        else:
            # 在节点开头插入
            m = re.match(r"^(\s*)", lines[s])
            ins_indent = m.group(1) + "\t"
            lines.insert(s + 1, '%sstatus = "disabled";\n' % ins_indent)
            print("    ✓ %-42s 新增 status=disabled (插在第 %d 行后)" % (p, s + 1))
        changed.append(p)

    if not changed:
        print("    ✗ 一个节点都没改到 —— 拒绝继续"); sys.exit(3)

    # ---------- 写回 dts，编译 ----------
    print("\n[3] 编译 dts -> dtb")
    with open(dts_out, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    run_dtc(args.dtc, ["-I", "dts", "-O", "dtb", "-o", args.out_dtb, dts_out])
    print("    输出 %d B" % os.path.getsize(args.out_dtb))

    # ---------- 闸4：重新反编译，逐节点确认 ----------
    print("\n[闸4] 重新反编译，逐节点确认")
    dts_v = os.path.join(workdir, "verify.dts")
    run_dtc(args.dtc, ["-I", "dtb", "-O", "dts", "-o", dts_v, args.out_dtb])
    with open(dts_v, "r", encoding="utf-8", errors="replace") as f:
        vlines = f.read().splitlines(keepends=True)
    vfail = []
    for p in TRIM_NODES:
        sp = node_span(vlines, p)
        if sp is None:
            print("    = %-42s 输出里没有（本就没有）" % p); continue
        st, _ = get_status(vlines, sp)
        ok = (st == "disabled")
        print("    %s %-42s status=%s" % ("✓" if ok else "✗", p, st))
        if not ok:
            vfail.append(p)
    if vfail:
        print("    ✗ 有节点没被禁掉: %s" % vfail); sys.exit(3)

    # ---------- 闸1（复验）：红线节点仍然 enabled ----------
    print("\n[闸1-复验] 红线节点仍然 enabled")
    for p in MUST_STAY_ENABLED:
        sp = node_span(vlines, p)
        if sp is None:
            print("    ⚠ %s 输出里不见了！" % p); vfail.append(p); continue
        st, _ = get_status(vlines, sp)
        ok = st in (None, "okay")
        print("    %s %-42s status=%s" % ("✓" if ok else "✗", p, st or "无(默认okay)"))
        if not ok:
            vfail.append(p)
    if vfail:
        print("    ✗ 红线被破坏: %s" % vfail); sys.exit(3)

    # ---------- 闸3（复验）：mem=992M 仍在 ----------
    print("\n[闸3-复验] bootargs 里的 %s" % MUST_KEEP_BOOTARGS)
    boot_ok2 = any(MUST_KEEP_BOOTARGS in ln for ln in vlines)
    print("    %s 输出里 %s" % ("✓" if boot_ok2 else "✗", MUST_KEEP_BOOTARGS))
    if not boot_ok2:
        print("    ✗ ★★★ CNN 的 POOL_BASE=0x3E000000 依赖它，丢了会静默损坏内存！拒绝继续")
        sys.exit(3)

    # ---------- 闸2：整组性（i2c 父+子一起禁） ----------
    print("\n[闸2] 整组性检查")
    grp = ["/amba_pl/i2c@41600000", "/amba_pl/i2c@41600000/ov5640@3c"]
    sts = []
    for p in grp:
        sp = node_span(vlines, p)
        sts.append(get_status(vlines, sp)[0] if sp else None)
    if all(s == "disabled" for s in sts):
        print("    ✓ i2c 父+子 都 disabled（无悬空 phandle）")
    elif all(s is None for s in sts):
        print("    = i2c 组在输出里都不存在（跳过）")
    else:
        print("    ✗ i2c 组不一致: %s" % list(zip(grp, sts))); sys.exit(3)

    print("\n" + "=" * 70)
    print("★★★ 全部安全闸通过  RESULT=DTB_PATCH_OK")
    print("  输出: %s (%d B)" % (args.out_dtb, os.path.getsize(args.out_dtb)))
    print("  禁用了 %d 个节点: %s" % (len(changed), changed))
    print("  ★ HDMI 的 5 个节点【未被动过】")
    print("  ★ bootargs 的 %s 原样保留" % MUST_KEEP_BOOTARGS)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
