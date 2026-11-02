#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_dtb_patch.py —— 设备树补丁生成器（PC 侧，用 Vivado 自带的 dtc.exe）

为什么不用 fdtput：
  实测我们板子上 fdtput / fdtget / dtc / devmem2 全部缺失
  （`which fdtput fdtget dtc devmem2` 全 MISSING），
  PC 上也没有 fdtput。所以走「反编译成 .dts → 文本改 → 编译回 .dtb」这条路。

  PC 上的 dtc：
    D:\\Xilinx\\2026.1\\Vivado\\bin\\dtc.exe   (228,780 B)   实测可用
    D:\\Xilinx\\2026.1\\Vivado\\bin\\dtc       (406,184 B)

两种模式：
  --mode keep   保留式：一个节点都不动，只做「反编译→编译」往返，
                用来验证 dtc 链路可用 + 确认往返后 LCD/音频/touch 链完好。
                ★ 合并方案若是「加法合并」（我们所有 PL IP 都保留），
                  这就是最终方案：不需要 disable 任何节点。
  --mode trim   删减式：把 HDMI / camera 这一组 9 个节点标成 disabled。
                ★ 合并方案若是「以他的 BD 为基」（删掉 camera/HDMI/i2c2 腾 Slice），
                  用这个。

★ 安全闸（脚本自带，任何一条不过就退出码非 0）：
  1. 输出 dtb 必须能重新反编译（说明结构合法）
  2. trim 模式下 9 个节点必须全部 status = "disabled"
  3. LCD 链 5 个节点（clk_wiz@43c30000 / v_tc@43c10000 / v_frmbuf_rd@43c20000 /
     PWM@43c00000 / gpio@41200000 / drm_pl_disp_lcd / atk_lcd_drm）
     必须仍然存在且不是 disabled
  4. ★ chosen/bootargs 必须仍含 mem=992M
     （992 MB = 0x3E000000，正是 cnn_linux.py 的 POOL_BASE；
      丢了这条 ⇒ CNN 的 DmaBuf 会写进 Linux 正在用的内存 ⇒ 崩）
  5. i2s / audio_formatter / i2c@e0005000(touch) 必须仍在且 enabled

用法：
  python make_dtb_patch.py <in.dtb> <out.dtb> --mode trim
  python make_dtb_patch.py <in.dtb> <out.dtb> --mode keep
  python make_dtb_patch.py <in.dtb> <out.dtb> --mode trim --dtc "D:\\Xilinx\\2026.1\\Vivado\\bin\\dtc.exe"
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- 常量
DEFAULT_DTC = r"D:\Xilinx\2026.1\Vivado\bin\dtc.exe"

# 要 disable 的 9 个节点 —— 全路径，与 his SCOPE_DUAL_DEPLOY.md 第二节一致
TRIM_NODES = [
    "/amba_pl/clk_wiz@43c80000",        # HDMI 动态时钟   <- 他 panic 就出在这
    "/amba_pl/v_tc@43c90000",           # HDMI 时序控制器
    "/amba_pl/v_frmbuf_wr@43c40000",    # 摄像头写入
    "/amba_pl/v_frmbuf_rd@43ca0000",    # HDMI framebuffer 读
    "/amba_pl/i2c@41600000",            # i2c2
    "/amba_pl/i2c@41600000/ov5640@3c",  # 摄像头传感器
    "/amba_pl/drm_pl_disp_hdmi",        # HDMI 显示封装
    "/amba_pl/atk_hdmi_drm",            # HDMI DRM
    "/amba_pl/vcap_dvp",                # 摄像头采集
]

# 必须【保持可用】的节点（LCD / 音频 / 触摸）—— 硬红线
MUST_STAY_ENABLED = [
    "/amba_pl/clk_wiz@43c30000",        # LCD pclk + mclk
    "/amba_pl/v_tc@43c10000",           # LCD 时序
    "/amba_pl/v_frmbuf_rd@43c20000",    # LCD framebuffer 读
    "/amba_pl/drm_pl_disp_lcd",         # LCD 显示封装
    "/amba_pl/atk_lcd_drm",             # LCD DRM（timing2 = 1024x600）
    "/amba_pl/PWM@43c00000",            # 背光 PWM
    "/amba_pl/gpio@41200000",           # LCD ID 读
    "/amba_pl/audio_formatter@43c50000",
    "/amba_pl/i2s_receiver@43c60000",
    "/amba_pl/i2s_transmitter@43c70000",
    # ★ 注意：触摸/音频这两条在 /amba/ 下（PS 侧），不在 /amba_pl/ 下
    "/amba/i2c@e0005000",                 # i2c-2：0x14 Goodix 触摸 + 0x38 FT5426（读 LCD ID）
    "/amba/i2c@e0004000",                 # i2c-1：0x10/0x50/0x51 ES8388
    "/amba/i2c@e0004000/es8388@10",
]

BOOTARGS_MUST_CONTAIN = "mem=992M"


# ---------------------------------------------------------------- 工具
def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def dtc_available(dtc):
    if os.path.isfile(dtc):
        return True
    # 退路：PATH 里找得到也行
    return shutil.which(dtc) is not None


def decompile(dtc, dtb, dts):
    rc, out, err = run([dtc, "-I", "dtb", "-O", "dts", "-o", dts, dtb])
    if rc != 0 or not os.path.exists(dts):
        raise SystemExit("dtc 反编译失败 rc=%d\n%s\n%s" % (rc, out, err))
    return dts


def compile_dts(dtc, dts, dtb):
    rc, out, err = run([dtc, "-I", "dts", "-O", "dtb", "-o", dtb, dts])
    if rc != 0 or not os.path.exists(dtb):
        raise SystemExit("dtc 编译失败 rc=%d\n%s\n%s" % (rc, out, err))
    return dtb


# ---------------------------------------------------------------- dts 解析
NODE_RE = re.compile(r"^\s*(?:[A-Za-z0-9_\+\-]+\s*:\s*)?([A-Za-z0-9_,\.\+\-@]+)\s*\{\s*$")
CLOSE_RE = re.compile(r"^\s*\};?\s*$")
PROP_RE = re.compile(r"^\s*([A-Za-z0-9_\+\-#,\.]+)\s*=")


class DtsDoc(object):
    """极简 dts 解析：只关心「每个节点块的起止行」和「块内有没有 status 属性」"""

    def __init__(self, lines):
        self.lines = lines
        self.blocks = {}        # 路径 -> (start_idx, end_idx, status_line_idx or None)
        self._parse()

    def _parse(self):
        stack = []              # [(name, start_idx, status_idx)]
        for i, ln in enumerate(self.lines):
            m = NODE_RE.match(ln)
            if m:
                stack.append([m.group(1), i, None])
                continue
            if CLOSE_RE.match(ln):
                if stack:
                    name, start, status = stack.pop()
                    path = "/" + "/".join([s[0] for s in stack] + [name])
                    if path.startswith("//"):
                        path = path[1:]
                    self.blocks[path] = (start, i, status)
                continue
            if stack:
                pm = PROP_RE.match(ln)
                if pm and pm.group(1) == "status":
                    stack[-1][2] = i

    def path_of(self, name):
        """按节点名找唯一路径（用于容错：调用方给 @43c80000 这种短名）"""
        hits = [p for p in self.blocks if p.rsplit("/", 1)[-1] == name]
        return hits

    def is_disabled(self, path):
        b = self.blocks.get(path)
        if not b:
            return None                     # 节点不存在
        st = b[2]
        if st is None:
            return False                    # 无 status 属性 => 默认 enabled
        return "disabled" in self.lines[st]

    def node_exists(self, path):
        return path in self.blocks


def set_disabled(doc, path):
    """把节点标成 disabled：有 status 就改，没有就在开括号后插入一行。

    ★★ 必须【按 start 索引从大到小】调用（见 apply_trim）。
       因为插入行会让后面所有行的索引 +1，而 doc.blocks 里存的是【原始】索引。
       从后往前改，就不会影响还没处理的行。
    """
    b = doc.blocks.get(path)
    if b is None:
        return False
    start, _end, status_idx = b
    if status_idx is not None:
        indent = re.match(r"^(\s*)", doc.lines[status_idx]).group(1)
        doc.lines[status_idx] = indent + 'status = "disabled";'
        return True
    # 插到节点开括号的下一行（= 该节点第一条属性之前，合法）
    indent = re.match(r"^(\s*)", doc.lines[start]).group(1) + "\t"
    doc.lines.insert(start + 1, indent + 'status = "disabled";')
    return True


def apply_trim(doc, paths):
    """★ 从后往前改，避免插入行导致索引错位。

    返回 (已改列表, 不存在列表)
    """
    order = sorted(
        [p for p in paths if p in doc.blocks],
        key=lambda p: doc.blocks[p][0],
        reverse=True,                     # 关键：倒序
    )
    changed = []
    for p in order:
        set_disabled(doc, p)
        changed.append(p)
    missing = [p for p in paths if p not in doc.blocks]
    return changed, missing


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_dtb")
    ap.add_argument("out_dtb")
    ap.add_argument("--mode", choices=("keep", "trim"), required=True)
    ap.add_argument("--dtc", default=DEFAULT_DTC)
    ap.add_argument("--workdir", default=None, help="中间 .dts 放哪里（默认重建后删除）")
    args = ap.parse_args()

    if not dtc_available(args.dtc):
        raise SystemExit("找不到 dtc：%s\n也没在 PATH 里。请用 --dtc 指定 Vivado 的 dtc.exe" % args.dtc)
    if not os.path.isfile(args.in_dtb):
        raise SystemExit("输入不存在：%s" % args.in_dtb)

    tmp = args.workdir or tempfile.mkdtemp(prefix="dtbpatch_")
    os.makedirs(tmp, exist_ok=True)

    print("=" * 74)
    print("make_dtb_patch.py  模式=%s" % args.mode)
    print("=" * 74)
    print("dtc      : %s" % args.dtc)
    print("输入 dtb : %s  (%d B  md5=%s)"
          % (args.in_dtb, os.path.getsize(args.in_dtb), md5(args.in_dtb)))
    print("中间目录 : %s" % tmp)
    print()

    dts0 = os.path.join(tmp, "orig.dts")
    decompile(args.dtc, args.in_dtb, dts0)
    with open(dts0, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines(keepends=True)

    doc = DtsDoc(lines)
    print("反编译 OK：%d 行，解析出 %d 个节点" % (len(lines), len(doc.blocks)))

    # ---- 打补丁
    if args.mode == "trim":
        print("\n-- 要 disable 的节点（内部按行号倒序应用，避免索引错位）--")
        changed, missing = apply_trim(doc, TRIM_NODES)
        for p in changed:
            print("  %-42s -> disabled" % p)
        for p in missing:
            print("  %-42s ★ 节点不存在（跳过，正常）" % p)
        if missing:
            print("\n  ⚠ 有 %d 个节点在输入 dtb 里不存在：%s" % (len(missing), ", ".join(missing)))
            print("    这在「已经删过一轮」的 dtb 上是正常的，不算错。")
    else:
        print("\n-- 保留式：不改任何节点，只做往返验证 --")

    # 重新解析（插入行后索引变了，重新来一遍最稳）
    doc2 = DtsDoc(lines)
    dts1 = os.path.join(tmp, "patched.dts")
    with open(dts1, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(lines))

    compile_dts(args.dtc, dts1, args.out_dtb)
    print("\n编译 OK : %s  (%d B  md5=%s)"
          % (args.out_dtb, os.path.getsize(args.out_dtb), md5(args.out_dtb)))

    # ---- 安全闸：重新反编译输出，逐节点核对
    print("\n" + "=" * 74)
    print("安全闸（任何一条不过 => 退出码 1，不要拿去上板）")
    print("=" * 74)
    dts2 = os.path.join(tmp, "verify.dts")
    decompile(args.dtc, args.out_dtb, dts2)
    with open(dts2, "r", encoding="utf-8", errors="replace") as f:
        vdoc = DtsDoc(f.read().splitlines(keepends=True))
        f.seek(0)
        vtext = f.read()

    fails = []

    # 闸1：反编译成功（上面没抛异常就是过）
    print("[PASS] 闸1 输出 dtb 能重新反编译")

    # 闸2：trim 模式下 9 个节点必须 disabled
    if args.mode == "trim":
        bad = []
        for p in TRIM_NODES:
            st = vdoc.is_disabled(p)
            if st is None:
                continue                       # 本来就不存在，OK
            if st is not True:
                bad.append(p)
        if bad:
            fails.append("闸2 这些节点没被 disabled：%s" % ", ".join(bad))
            print("[FAIL] 闸2 节点 disabled 校验，未通过：%s" % ", ".join(bad))
        else:
            print("[PASS] 闸2 需 disable 的节点全部 status=disabled（或本就不存在）")
    else:
        print("[SKIP] 闸2 保留式不检查 disabled")

    # 闸3：LCD 链必须仍在且 enabled（硬红线）
    bad3 = []
    for p in MUST_STAY_ENABLED:
        st = vdoc.is_disabled(p)
        if st is None:
            bad3.append("%s (节点没了!)" % p)
        elif st is True:
            bad3.append("%s (被 disabled 了!)" % p)
    if bad3:
        fails.append("闸3 LCD/音频/触摸链被破坏：%s" % "; ".join(bad3))
        print("[FAIL] 闸3 LCD/音频/触摸链：%s" % "; ".join(bad3))
    else:
        print("[PASS] 闸3 LCD(%d 节点)/音频/触摸链全部仍在且 enabled" % len(MUST_STAY_ENABLED))

    # 闸4：bootargs 必须仍含 mem=992M（CNN DmaBuf 存放区）
    if BOOTARGS_MUST_CONTAIN in vtext:
        print("[PASS] 闸4 chosen/bootargs 仍含 %s（CNN DmaBuf @0x3E000000 的依赖）"
              % BOOTARGS_MUST_CONTAIN)
    else:
        fails.append("闸4 bootargs 丢了 %s —— CNN 会写到 Linux 内存上，绝不能上板" % BOOTARGS_MUST_CONTAIN)
        print("[FAIL] 闸4 bootargs 里找不到 %s" % BOOTARGS_MUST_CONTAIN)

    # 闸5：/amba_pl 节点数对比（提示性，不算 fail）
    n_before = len([p for p in doc.blocks if p.startswith("/amba_pl/")])
    n_after = len([p for p in vdoc.blocks if p.startswith("/amba_pl/")])
    print("[INFO] 闸5 /amba_pl 节点数：改前 %d -> 改后 %d（dtc 会重排 phandle，数量应一致）"
          % (n_before, n_after))

    print()
    if fails:
        print("！！ 未通过，禁止上板 ！！")
        for x in fails:
            print("   - %s" % x)
        return 1

    print("★ 全部安全闸通过。产物：%s" % os.path.abspath(args.out_dtb))
    if not args.workdir:
        print("中间 .dts 保留在：%s（想删就删，不影响）" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
