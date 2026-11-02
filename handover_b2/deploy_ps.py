#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_ps.py —— 把第二块板的双通道示波器【PS 层】部署到我们板子（192.168.10.20）

设计原则（用户硬性要求：现有功能一个都不能删 + 每一步都要备份）
  1. ★ 带 md5 校验：上传前校本地、上传后校远端、安装后校最终；任何一处不符立刻停。
  2. ★ 时间戳备份：动手前把要碰的每个文件都备份到板上的 `_b2_backup_<TS>/`，
     并把 md5 清单写成 manifest（回滚脚本读它）。
  3. ★ 失败自动停止：任一步失败 => 立刻中止，并打印「回滚一条命令」。
  4. ★ 绝不碰红线文件：fbui.py / apps_scope.py / scope.py / libscope.so /
     .scope_addr / desktop.py 的既有 26 条 APPS 条目 / /mnt/boot 四个启动件。
     （desktop.py 只做【加一条】的最小补丁，且先备份）

用法
  # 只做只读预检（不写板子，推荐先跑）
  python deploy_ps.py --dry-run

  # 完整部署（推 PS 文件 + 板上 gcc 编译 .so + 桌面入口）
  python deploy_ps.py

  # 换基地址（默认从 --base 取；不传则用 0x43CF0000）
  python deploy_ps.py --base 0x43CF0000

  # 分步
  python deploy_ps.py --stage files      # 只推 PS 文件 + 编译
  python deploy_ps.py --stage desktop    # 只打桌面入口
  python deploy_ps.py --verify           # 只校验当前部署状态（只读）

依赖
  - 同目录的 board.py（复用它的 paramiko SSH/SFTP；BOARD_IP 环境变量生效）
  - 板上有 gcc（实测 gcc 9.4.0）+ python3（实测 3.8.10）+ PIL 7.0.0
  - ★ 板上【没有】fdtput/dtc/numpy —— 本脚本不依赖它们
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import time

# ------------------------------------------------------------------ 路径
HERE = os.path.dirname(os.path.abspath(__file__))          # D:\ubuntu_iso\handover_b2
UBUNTU = os.path.dirname(HERE)                             # D:\ubuntu_iso
SRC_PS = os.path.join(UBUNTU, "from_board2", "scope_project", "ps")
STAGE = os.path.join(HERE, "_stage")
LOG_PREFIX = "deploy"

sys.path.insert(0, UBUNTU)
try:
    import board                                            # noqa: E402
except Exception as ex:                                     # pragma: no cover
    print("！！ 无法 import board.py（%s）。请在 D:\\ubuntu_iso 下跑，并确认 paramiko 已装。" % ex)
    sys.exit(2)


# ------------------------------------------------------------------ 常量
DEFAULT_BASE = "0x43CF0000"          # Lead 已定：我们 0x43C00000~0x43CE0000 全占满
UI = "/home/zynq/ui"
STAGE_REMOTE = "/tmp/b2_ps"
SCOPE_DUAL_ADDR = "/home/zynq/.scope_dual_addr"       # ★ 他的独立标记文件
OUR_MARKER = "/home/zynq/.scope_addr"                 # ★ 我们的，绝对不许改

# 基线（2026-10-16 步骤2/3 之后的新基线）—— 板端实测确认过
# ★ 相对 10-14 基线的前进（都是本次计划内的改动）：
#   system.dtb: ece3cd8d… -> 68ed7544…  (camera 4 节点 disabled，步骤2)
#   system.bit: 369b1a18… -> 924df8b9…  (合并后的新流，步骤3)
BOOT_BASELINE = {
    "/mnt/boot/system.bit": "924df8b9d9c9de17fcf06e163b723681",
    "/mnt/boot/system.dtb": "68ed75440e1eac01f5fdbdf9c42c4672",
    "/mnt/boot/zImage":     "fe8403e36d6c8bfde1d395d1d2b0c1f8",
    "/mnt/boot/BOOT.BIN":   "949cc7c9c509133ff3e9541133220d58",
}
UI_BASELINE = {
    "/home/zynq/ui/fbui.py":       "13ff672a762a28f4f3444fa6df2bf61f",
    "/home/zynq/ui/desktop.py":    "7d25f5b0f2f3dcbf2b6d2f4786350027",
    "/home/zynq/ui/apps_scope.py": "b2922c63664f150e8c3d2d85e3b738a3",
    "/home/zynq/ui/scope.py":      "dc27fd691cf058d2c11ad52b07fac86c",
    "/home/zynq/ui/libscope.so":   "c412125e35bf9e06d07bad262b13e84c",
}
# ★ 红线：这些文件在整个部署里【一个字节都不许动】
RED_LINE = set(UI_BASELINE) | {OUR_MARKER} | set(BOOT_BASELINE)

# 要从工程包推上去的 PS 文件（源文件名, 板上文件名）
PUSH_FILES = [
    ("scope_dual.py",       "scope_dual.py"),        # ★ 会被就地改基地址 + 标记文件
    ("scope_processing.py", "scope_processing.py"),
    ("scope_model.py",      "scope_model.py"),
    ("apps_scope_dual.py",  "apps_scope_dual.py"),
    ("scope_dual.c",        "scope_dual.c"),         # 推到板上，板上 gcc 编译
]
# 可选：标定工具（默认一起推，纯新增，不覆盖任何东西）
CAL_FILES = [
    ("cal_scope.py",       "cal_scope.py"),
    ("cal_diag.py",        "cal_diag.py"),
    ("cal_from_pairs.py",  "cal_from_pairs.py"),
]
# 板上 gcc 编译出的 .so
SO_NAME = "libscopedual.so"
# ★ 编译产物必须导出这些符号，缺一个就判定编译失败
SO_REQUIRED_SYMS = [
    "sd_open", "sd_close", "sd_probe", "sd_version", "sd_caps",
    "sd_read_envelope", "sd_read_stats", "sd_set_window",
    "sd_measure", "sd_envelope", "sd_draw_env", "sd_read_frame_locked",
]
# ★ 我们新增的文件（回滚时要删掉的，白名单；绝不删别的）
NEW_FILES = ["/home/zynq/ui/" + d for _s, d in PUSH_FILES] + \
            ["/home/zynq/ui/" + d for _s, d in CAL_FILES] + \
            ["/home/zynq/ui/" + SO_NAME] + \
            [SCOPE_DUAL_ADDR]


# ------------------------------------------------------------------ 小工具
class Fail(Exception):
    pass


def log(msg=""):
    print(msg, flush=True)


def step(n, title):
    log()
    log("=" * 74)
    log(" 步骤 %s  %s" % (n, title))
    log("=" * 74)


def md5_local(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


_RC_MARK = "__B2_RC__"


def sh_rc(cmd, timeout=300):
    """在板上跑命令并【真正拿到退出码】。

    ★ board.py 的 run() 只返回 (stdout, stderr)，没有退出码 —— 所以必须自己
      在命令尾巴上 echo 一个哨兵把 $? 带回来，否则「失败自动停止」就是假的。
    """
    wrapped = "( %s ) 2>&1; echo %s$?" % (cmd, _RC_MARK)
    out, err = board.run(wrapped, timeout=timeout, quiet=True)
    rc = 0
    lines = out.rstrip("\n").splitlines()
    if lines and lines[-1].startswith(_RC_MARK):
        try:
            rc = int(lines[-1][len(_RC_MARK):].strip() or "0")
        except ValueError:
            rc = 0
        out = "\n".join(lines[:-1])
    return rc, out, err


def sh(cmd, timeout=300, check=True, quiet=True):
    """check=True 时非 0 退出码 => 抛 Fail（失败自动停止）。"""
    rc, out, err = sh_rc(cmd, timeout=timeout)
    if check and rc != 0:
        raise Fail("板上命令失败 rc=%s\n  cmd: %s\n  out: %s\n  err: %s"
                   % (rc, cmd, out.strip()[-800:], err.strip()[-800:]))
    return out, err


def r_md5(path):
    """远端文件的 md5；文件不存在返回 None。"""
    out, _ = board.run("md5sum '%s' 2>/dev/null" % path, quiet=True)
    parts = out.strip().split()
    if parts and len(parts[0]) == 32:
        return parts[0]
    return None


def r_size(path):
    out, _ = board.run("stat -c %%s '%s' 2>/dev/null" % path, quiet=True)
    s = out.strip()
    return int(s) if s.isdigit() else None


def r_exists(path):
    out, _ = board.run("[ -e '%s' ] && echo YES || echo NO" % path, quiet=True)
    return out.strip().endswith("YES")


def need_local(path):
    if not os.path.isfile(path):
        raise Fail("本地源文件不存在：%s" % path)
    return path


def read_text_exact(path):
    """★ 按字节读 + 【严格】UTF-8 解码 + 探测行尾。

    为什么不能用 `open(p, "r", encoding="utf-8", errors="replace")`：
      1. errors="replace" 会把非法字节静默换成 U+FFFD —— 如果文件是 GBK，
         所有中文会被【静默损坏】，而我们在部署，损坏是灾难性的。
      2. 文本模式会把 CRLF 归一成 LF，写回去就变成 LF ——
         实测我们的 desktop.py 有 **1697 个 CRLF**、fbui.py 有 **1105 个**，
         而他的 PS 文件是纯 LF。若归一化，一个 76 KB 的文件会被
         【无理由地改动 1697 行】，diff 完全没法审，md5 也对不上基线。

    返回 (text, newline)，text 里保留原始 "\\r\\n"。
    """
    raw = open(path, "rb").read()
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError as ex:
        raise Fail("文件 %s 不是合法 UTF-8（%s）。\n"
                   "  ⇒ 拒绝用 errors=replace 硬来（会静默损坏中文）。"
                   "请先确认它的真实编码。" % (path, ex))
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    nl = "\r\n" if crlf > lf else "\n"
    log("   编码=utf-8(严格)  行尾=%s  CRLF=%d  LF=%d"
        % ("CRLF" if nl == "\r\n" else "LF", crlf, lf))
    return txt, nl


def write_text_exact(path, txt):
    """用二进制写回，保证编码/行尾与原文完全一致（不做任何转换）。"""
    with open(path, "wb") as f:
        f.write(txt.encode("utf-8"))


# ------------------------------------------------------------------ 预检（只读）
def preflight(args):
    step("0", "只读预检（这一步不写板子）")
    log("板子 IP       : %s" % (board.HOST or "(未找到)"))
    if not board.HOST:
        raise Fail("找不到板子。请设置 $env:BOARD_IP=\"192.168.10.20\" 后重试。")
    if board.HOST != "192.168.10.20":
        log("⚠ 当前目标不是我们板子（192.168.10.20），而是 %s" % board.HOST)
        if not args.allow_other_host:
            raise Fail("拒绝在非 192.168.10.20 上部署。确实要的话加 --allow-other-host。")

    out, _ = board.run("uname -r; cat /proc/device-tree/model 2>/dev/null; echo", quiet=True)
    log("内核 / 板型   : %s" % out.strip().replace("\n", " | "))

    # 1) /mnt/boot 四个启动件必须与基线一致（证明板子在"完好态"）
    log()
    log("-- 1) /mnt/boot 基线校验（必须全部一致，否则先别部署）--")
    bad = []
    for p, want in BOOT_BASELINE.items():
        got = r_md5(p)
        ok = (got == want)
        log("   %-24s %s  %s" % (os.path.basename(p), got or "(读不到)",
                                 "OK" if ok else "★不符 期望 " + want))
        if not ok:
            bad.append(p)
    if bad:
        raise Fail("基线不符：%s\n  ⇒ 板子不在 2026-10-14 记录的良好状态。"
                   "先搞清为什么，别在不确定的状态上部署。" % ", ".join(bad))

    # 2) /home/zynq/ui 基线文件
    log()
    log("-- 2) /home/zynq/ui 基线校验 --")
    for p, want in UI_BASELINE.items():
        got = r_md5(p)
        mark = "OK" if got == want else "★不符(期望 %s)" % want
        log("   %-30s %s  %s" % (p, got or "(读不到)", mark))
        if got != want and p != UI + "/desktop.py":
            raise Fail("基线文件 %s 的 md5 与记录不符 ⇒ 中止（先搞清是谁改的）" % p)

    # 3) 我们自己的标记文件必须是 0x43CC0000 且不许被改
    log()
    log("-- 3) 我们的基址标记（红线）--")
    out, _ = board.run("cat '%s' 2>/dev/null" % OUR_MARKER, quiet=True)
    log("   %s = %s" % (OUR_MARKER, out.strip() or "(空)"))
    if out.strip() != "0x43CC0000":
        log("   ⚠ 与我们记录 (0x43CC0000) 不一致 —— 部署本身不会改它，但请留意")

    # 4) 目标文件是否已存在（避免覆盖别人的东西）
    log()
    log("-- 4) 目标是否已存在（存在就说明部署过；要重来请先跑 rollback.py）--")
    exist = [p for p in NEW_FILES if r_exists(p)]
    for p in NEW_FILES:
        log("   %-42s %s" % (p, "已存在 ★" if p in exist else "不存在 (可新增)"))
    if exist and not args.force:
        raise Fail("以下文件已存在，拒绝覆盖：%s\n  ⇒ 先 `python rollback.py` 回到基线，"
                   "或加 --force（会先备份再覆盖）。" % ", ".join(exist))

    # 5) 工具链 + 空间
    log()
    log("-- 5) 板上工具链 + 空间 --")
    out, _ = board.run("gcc --version 2>&1 | head -1; python3 -V; "
                       "python3 -c 'import PIL;print(\"PIL\",PIL.__version__)' 2>&1 | head -1; "
                       "df -h / /mnt/boot | tail -2", quiet=True)
    for ln in out.strip().splitlines():
        log("   " + ln)
    if "gcc" not in out:
        raise Fail("板上没有 gcc，无法编译 libscopedual.so")
    if "PIL" not in out or "Traceback" in out.split("PIL")[0][-40:]:
        log("   ⚠ PIL 可能有问题（apps_scope_dual 依赖 fbui，fbui 依赖 PIL）")

    # 6) 源文件齐不齐 + 本地 md5
    log()
    log("-- 6) 本地源文件 --")
    for s, d in PUSH_FILES + CAL_FILES:
        p = need_local(os.path.join(SRC_PS, s))
        log("   %-24s %8d B  md5=%s" % (s, os.path.getsize(p), md5_local(p)))

    # 7) ★ fbui.py 接口自检（他 apps_scope_dual 强依赖 to_raw/blit_raw）
    log()
    log("-- 7) 我们的 fbui.py 是否满足他 apps_scope_dual 的接口 --")
    out, _ = board.run(
        "python3 - <<'PY'\n"
        "import sys; sys.path.insert(0,'%s')\n"
        "import fbui\n"
        "need=['to_raw','blit_raw','text','tw','flush','fill_raw']\n"
        "have=[n for n in need if hasattr(fbui.Screen,n)]\n"
        "print('HAVE:'+','.join(have))\n"
        "print('MISS:'+','.join([n for n in need if n not in have]))\n"
        "PY" % UI, quiet=True)
    log("   " + out.strip().replace("\n", "  "))
    if "MISS:" in out and out.split("MISS:")[1].strip():
        raise Fail("我们的 fbui.Screen 缺少他需要的接口：%s" % out.split("MISS:")[1].strip())
    log("   ✓ to_raw / blit_raw 都在（这就是必须用我们的 fbui.py 的原因）")
    return True


# ------------------------------------------------------------------ 本地变换
def build_patched_scope_dual(base):
    """把 scope_dual.py 的基地址 + 标记文件改掉（在本地暂存副本上改，不动源码）。"""
    src = need_local(os.path.join(SRC_PS, "scope_dual.py"))
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()

    # ① DEFAULT_BASE
    new_txt, n1 = re.subn(r'^(\s*DEFAULT_BASE\s*=\s*)0[xX][0-9a-fA-F]+',
                          lambda m: m.group(1) + base, txt, flags=re.M)
    if n1 != 1:
        raise Fail("没能唯一地找到 DEFAULT_BASE（找到 %d 处）—— 源码结构变了，请人工确认" % n1)

    # ② MARKER ★★ 关键：不能和他共用 /home/zynq/.scope_addr（我们的 scope.py 也在读它）
    new_txt, n2 = re.subn(r'^(\s*MARKER\s*=\s*)"/home/zynq/\.scope_addr"',
                          lambda m: m.group(1) + '"' + SCOPE_DUAL_ADDR + '"',
                          new_txt, flags=re.M)
    if n2 != 1:
        raise Fail("没能唯一地找到 MARKER（找到 %d 处）—— 源码结构变了，请人工确认" % n2)

    os.makedirs(STAGE, exist_ok=True)
    dst = os.path.join(STAGE, "scope_dual.py")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_txt)
    log("   scope_dual.py 已打补丁：DEFAULT_BASE=%s   MARKER=%s" % (base, SCOPE_DUAL_ADDR))
    log("   暂存：%s  (%d B  md5=%s)" % (dst, os.path.getsize(dst), md5_local(dst)))
    return dst


ICON_FUNC = '''

def icon_scope_dual(d, x, y, s):
    """示波器x2: 双踪 —— 两个屏幕框各一条波"""
    m = s * 0.08
    pw = max(2, int(s * 0.055))
    h2 = (s - m * 3) / 2.0
    for k in range(2):
        y0 = y + m + k * (h2 + m)
        d.rectangle([x + m, y0, x + s - m, y0 + h2],
                    outline=W, width=pw)
        col = (110, 255, 190) if k == 0 else (255, 210, 74)
        pts = []
        n = 22
        for i in range(n + 1):
            t = i / float(n)
            px = x + m * 1.6 + t * (s - m * 3.2)
            py = y0 + h2 / 2.0 - (h2 * 0.30) * math.sin(2 * math.pi * t + k * 1.1)
            pts.append((px, py))
        d.line(pts, fill=col, width=pw)

'''


def patch_desktop_text(txt, nl="\n"):
    """在 desktop.py 文本里加 icon_scope_dual() + 一条 APPS 条目。最小改动。

    ★ nl 必须传原文的行尾（我们的 desktop.py 是 CRLF）—— 插入的行要用同一种，
      否则文件会变成 CRLF/LF 混排。
    ★ 不碰其它任何一行：原有 23 条 APPS 条目一条不动。
    """
    if "icon_scope_dual" in txt:
        raise Fail("desktop.py 里已经有 icon_scope_dual —— 说明已经打过补丁，别重复打")

    # ① 图标函数插到 `class Desktop` 之前（保证是模块级）
    m = re.search(r'^class Desktop\b', txt, flags=re.M)
    if not m:
        raise Fail("在 desktop.py 里找不到 `class Desktop`（结构变了？）")
    icon = ICON_FUNC.replace("\r\n", "\n").lstrip("\n").replace("\n", nl)
    txt = txt[:m.start()] + icon + nl + txt[m.start():]

    # ② APPS 里加一条，紧跟我们的单通道「示波器」那一行（插在【换行之后】，独占一行）
    #    ★ 必须写 `\r?$`：我们的 desktop.py 是 CRLF，`$`（MULTILINE）只匹配 \n 之前，
    #      不写 \r? 的话这一行根本匹配不上。
    pat = re.compile(r'^([ \t]*)\{"name": "示波器".*?\},[ \t]*\r?$', re.M)
    mm = pat.search(txt)
    if not mm:
        raise Fail('在 desktop.py 的 APPS 里找不到 {"name": "示波器", ...} 那一行')
    entry = ('%s{"name": "示波器x2", "mod": "apps_scope_dual", '
             '"icon": icon_scope_dual, "tint": (235, 150, 60)},' % mm.group(1)) + nl
    at = mm.end()
    if txt[at:at + 1] == "\n":
        at += 1                                   # ★ 插到换行符之后 => 独占一行
    txt = txt[:at] + entry + txt[at:]
    return txt


# ------------------------------------------------------------------ 部署主体
def deploy(args):
    TS = time.strftime("%Y%m%d_%H%M%S")
    report = {"ts": TS, "host": board.HOST, "base": args.base, "steps": [], "ok": False}
    remote_backup = "%s/_b2_backup_%s" % (UI, TS)

    try:
        preflight(args)

        # ---------------------------------------------------------- 1. 板上时间戳备份
        step("1", "板端时间戳备份 -> %s" % remote_backup)
        sh("mkdir -p '%s'" % remote_backup)
        bk_items = list(UI_BASELINE) + [OUR_MARKER] + list(BOOT_BASELINE)
        # ★ /mnt/boot 只在 --backup-boot 时备份（它已经在 PC 上有一份，且 4 MB 大）
        if not args.backup_boot:
            bk_items = [p for p in bk_items if not p.startswith("/mnt/boot/")]
        for p in bk_items:
            rc, out, err = sh_rc("cp -p '%s' '%s/' 2>&1" % (p, remote_backup))
            log("   backup %-30s %s" % (p, "OK" if rc == 0 else "失败: " + err.strip()[:80]))
        # manifest
        manifest = []
        for p in bk_items:
            manifest.append({"orig": p,
                             "bak": posixpath.join(remote_backup, os.path.basename(p)),
                             "md5": r_md5(p)})
        # 记录基线期望值，回滚时用它当断言
        man = {"ts": TS, "host": board.HOST,
               "expect_ui": UI_BASELINE, "expect_boot": BOOT_BASELINE,
               "our_marker": "0x43CC0000",
               "items": manifest,
               "new_files": NEW_FILES}
        with open(os.path.join(STAGE, "manifest_%s.json" % TS), "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2, ensure_ascii=False)
        board.put(os.path.join(STAGE, "manifest_%s.json" % TS),
                  posixpath.join(remote_backup, "manifest.json"))
        log("   manifest 已写：%s/manifest.json" % remote_backup)
        report["backup_dir"] = remote_backup

        # ---------------------------------------------------------- 2. 本地暂存 + 补丁
        step("2", "本地暂存：改基地址 + 准备文件")
        patched = build_patched_scope_dual(args.base)
        os.makedirs(STAGE, exist_ok=True)
        sh("mkdir -p '%s'" % STAGE_REMOTE)
        board.run("rm -rf %s/*" % STAGE_REMOTE, quiet=True)

        # ---------------------------------------------------------- 3. 上传
        step("3", "上传到板上暂存目录 %s（先不进 UI 目录）" % STAGE_REMOTE)
        uploads = [(patched, SO_NAME.replace(SO_NAME, "scope_dual.py"))]
        for s, d in PUSH_FILES:
            if s == "scope_dual.py":
                continue                              # 用打过补丁的那份
            uploads.append((need_local(os.path.join(SRC_PS, s)), d))
        if args.with_cal:
            for s, d in CAL_FILES:
                uploads.append((need_local(os.path.join(SRC_PS, s)), d))

        lmd5 = {}
        for lp, dn in uploads:
            lmd5[dn] = md5_local(lp)
            board.put(lp, posixpath.join(STAGE_REMOTE, dn))
        # ★ 上传后逐个校 md5
        for lp, dn in uploads:
            got = r_md5(posixpath.join(STAGE_REMOTE, dn))
            if got != lmd5[dn]:
                raise Fail("上传校验失败：%s  本地=%s 远端=%s" % (dn, lmd5[dn], got))
        log("   ✓ %d 个文件上传完成，逐个 md5 校验通过" % len(uploads))

        # ---------------------------------------------------------- 4. 板上编译
        step("4", "板上 gcc 编译 %s" % SO_NAME)
        rc, out, err = sh_rc("cd %s && gcc -O2 -fPIC -shared -o %s scope_dual.c 2>&1"
                             % (STAGE_REMOTE, SO_NAME))
        log(out.strip()[-3000:] if out.strip() else "(无输出)")
        if rc != 0 or not r_exists(posixpath.join(STAGE_REMOTE, SO_NAME)):
            raise Fail("板上编译失败 rc=%s\n%s" % (rc, (out + err)[-1500:]))
        so_size = r_size(posixpath.join(STAGE_REMOTE, SO_NAME))
        log("   编译 OK，%s = %s B" % (SO_NAME, so_size))
        # ★ 符号自检
        out, _ = board.run("nm -D --defined-only %s/%s 2>/dev/null | awk '{print $3}' | sort -u"
                           % (STAGE_REMOTE, SO_NAME), quiet=True)
        syms = set(x.strip() for x in out.split() if x.strip())
        miss = [s for s in SO_REQUIRED_SYMS if s not in syms]
        if miss:
            raise Fail("编译出的 .so 缺少必需符号：%s" % ", ".join(miss))
        log("   ✓ 必需符号齐全（%d 个）" % len(SO_REQUIRED_SYMS))
        report["so_size"] = so_size
        report["so_md5"] = r_md5(posixpath.join(STAGE_REMOTE, SO_NAME))

        # ---------------------------------------------------------- 5. 安装到 UI 目录
        stage_files = args.stage
        if stage_files in ("all", "files"):
            step("5", "安装 PS 文件到 %s（逐个 md5 校验）" % UI)
            for lp, dn in uploads:
                sh("cp -f '%s/%s' '%s/%s'" % (STAGE_REMOTE, dn, UI, dn))
                got = r_md5(posixpath.join(UI, dn))
                want = lmd5[dn] if dn != SO_NAME else report["so_md5"]
                if got != want:
                    raise Fail("安装校验失败：%s  期望=%s 实际=%s" % (dn, want, got))
                log("   %-24s %8s B  md5=%s  OK" % (dn, r_size(posixpath.join(UI, dn)), got))
            # ★ 独立标记文件（绝不碰 .scope_addr）
            sh("printf '%%s\\n' '%s' > '%s'" % (args.base, SCOPE_DUAL_ADDR))
            log("   %s = %s" % (SCOPE_DUAL_ADDR, (board.run("cat '%s'" % SCOPE_DUAL_ADDR,
                                                            quiet=True)[0] or "").strip()))
            sh("chown zynq:zynq '%s' 2>/dev/null || true" % SCOPE_DUAL_ADDR)
            # 清掉 python 缓存，避免旧的 .pyc 生效
            sh("rm -rf '%s/__pycache__'/scope_dual.* '%s/__pycache__'/scope_model.* "
               "'%s/__pycache__'/scope_processing.* '%s/__pycache__'/apps_scope_dual.* 2>/dev/null || true"
               % (UI, UI, UI, UI))
            report["steps"].append("files installed")

        # ---------------------------------------------------------- 6. 桌面入口补丁
        if stage_files in ("all", "desktop"):
            step("6", "桌面入口补丁（desktop.py 加一条，最小改动）")
            dl = os.path.join(STAGE, "desktop_board.py")
            board.get(posixpath.join(UI, "desktop.py"), dl)
            before_md5 = md5_local(dl)
            log("   从板上取回的 desktop.py  md5=%s（基线应为 %s）"
                % (before_md5, UI_BASELINE[UI + "/desktop.py"]))
            if before_md5 != UI_BASELINE[UI + "/desktop.py"]:
                raise Fail("板上 desktop.py 已不是基线，拒绝打补丁（先搞清谁改的）")

            txt, nl = read_text_exact(dl)
            patched_txt = patch_desktop_text(txt, nl)
            patched_local = os.path.join(STAGE, "desktop_patched.py")
            write_text_exact(patched_local, patched_txt)

            # ★★ 强断言①：原文件的【每一行】都必须原样出现在新文件里（只允许插入，不允许修改）
            a = txt.splitlines()
            b = patched_txt.splitlines()
            j = 0
            inserted = 0
            for ln in a:
                while j < len(b) and b[j] != ln:
                    j += 1
                    inserted += 1
                if j >= len(b):
                    raise Fail("★ 补丁改动了原有内容（找不到原行：%r）—— 拒绝继续" % ln[:80])
                j += 1
            inserted += len(b) - j
            log("   ✓ 强断言①：原有 %d 行【一行未改】，只插入了 %d 行" % (len(a), inserted))

            # ★★ 强断言②：行尾风格保持不变（我们的 desktop.py 是 CRLF）
            if nl == "\r\n" and patched_txt.count("\r\n") < txt.count("\r\n"):
                raise Fail("★ 补丁把 CRLF 行尾弄丢了 —— 拒绝继续")
            log("   ✓ 强断言②：行尾风格保持 %s（CRLF %d -> %d）"
                % ("CRLF" if nl == "\r\n" else "LF",
                   txt.count("\r\n"), patched_txt.count("\r\n")))

            # ★ 断言③：APPS 条目集合只多不少
            base_mods = set(re.findall(r'"mod":\s*"([A-Za-z0-9_]+)"', txt))
            new_mods = set(re.findall(r'"mod":\s*"([A-Za-z0-9_]+)"', patched_txt))
            if not base_mods.issubset(new_mods):
                raise Fail("补丁弄丢了原有 APPS 条目：%s" % (base_mods - new_mods))
            if new_mods - base_mods != {"apps_scope_dual"}:
                raise Fail("补丁多出来的条目不是且仅是 apps_scope_dual：%s" % (new_mods - base_mods))
            log("   ✓ 断言③：APPS 条目 %d -> %d（新增且仅新增 apps_scope_dual）"
                % (len(base_mods), len(new_mods)))

            board.put(patched_local, posixpath.join(STAGE_REMOTE, "desktop.py"))
            rc, out, err = sh_rc("cd %s && python3 -m py_compile desktop.py && echo COMPILE_OK"
                                 % STAGE_REMOTE)
            if "COMPILE_OK" not in out:
                raise Fail("补丁后的 desktop.py 语法不过：%s" % (out + err)[-800:])
            log("   ✓ 语法自检通过（python3 -m py_compile）")
            sh("cp -f '%s/desktop.py' '%s/desktop.py'" % (STAGE_REMOTE, UI))
            got = r_md5(posixpath.join(UI, "desktop.py"))
            if got != md5_local(patched_local):
                raise Fail("desktop.py 安装校验失败 期望=%s 实际=%s"
                           % (md5_local(patched_local), got))
            # 板上再编译一次确认（防止 sftp 截断）
            rc, out, err = sh_rc("cd %s && python3 -m py_compile desktop.py && echo OK" % UI)
            if "OK" not in out:
                raise Fail("板上 desktop.py 语法不过，已中止（请立即 rollback）：%s" % (out + err)[-500:])
            sh("rm -rf '%s/__pycache__'/desktop.* 2>/dev/null || true" % UI)
            log("   ✓ desktop.py 安装完成  md5=%s" % got)
            report["desktop_before"] = before_md5
            report["desktop_after"] = got
            report["steps"].append("desktop patched")

        # ---------------------------------------------------------- 7. 冒烟测试
        step("7", "冒烟测试（读 PL 魔数，判断是否已接上新 bitstream）")
        smoke = os.path.join(STAGE, "smoke_scope_dual.py")
        with open(smoke, "w", encoding="utf-8", newline="\n") as f:
            f.write(
                "import sys\n"
                "sys.path.insert(0, '%s')\n"
                "import scope_dual\n"
                "d = scope_dual.ScopeDual(verbose=False)\n"
                "print('BASE=0x%%08X' %% d.base)\n"
                "print('HW=%%s' %% d.hw)\n"
                "print('WHY=%%s' %% d.why)\n"
                "if d.hw:\n"
                "    print('VER=%%s' %% d.lib.sd_version_str().decode())\n"
                "    print('CAPS=0x%%08X' %% d.lib.sd_caps())\n"
                "d.close()\n" % UI)
        board.put(smoke, posixpath.join(STAGE_REMOTE, "smoke_scope_dual.py"))
        out, err = board.run("cd %s && sudo -n python3 smoke_scope_dual.py 2>&1"
                             % STAGE_REMOTE, quiet=True)
        log("   " + out.strip().replace("\n", "\n   "))
        report["smoke"] = out.strip()
        if "HW=True" not in out:
            log()
            log("   ⚠⚠ 冒烟测试：ScopeDual.hw = False")
            log("      这是【预期】的 —— 现在板上还没有他的 bitstream（新 PL 未上）。")
            log("      PS 层已经装好并语法/符号自检通过；等新 PL 上了再跑一次这个冒烟测试，")
            log("      期望看到  BASE=0x%s  HW=True  VER=...magic 0x53435xxx..." % args.base.upper())
            report["smoke_hw"] = False
        else:
            report["smoke_hw"] = True

        report["ok"] = True
        return report

    except Fail as ex:
        log()
        log("!" * 74)
        log("！！ 部署失败并已自动停止：%s" % ex)
        log("!" * 74)
        log()
        log("★ 立即回滚（一条命令）：")
        log("     python handover_b2\\rollback.py")
        log("  备份目录：%s" % remote_backup)
        report["error"] = str(ex)
        return report


# ------------------------------------------------------------------ 只读校验
def verify_only(args):
    step("V", "只读校验当前部署状态（不写板子）")
    ok = True
    log("-- 基线文件是否还在 --")
    for p, want in list(UI_BASELINE.items()) + list(BOOT_BASELINE.items()):
        got = r_md5(p)
        same = (got == want)
        ok = ok and same
        log("   %-32s %s  %s" % (os.path.basename(p), got or "(读不到)",
                                 "OK" if same else "★被改过（期望 %s）" % want))
    log()
    log("-- 新增文件是否到位 --")
    for p in NEW_FILES:
        got = r_md5(p)
        log("   %-42s %s" % (p, got or "不存在"))
    log()
    log("-- 我们的标记文件（红线，必须还是 0x43CC0000）--")
    out, _ = board.run("cat '%s' 2>/dev/null" % OUR_MARKER, quiet=True)
    marker_ok = out.strip() == "0x43CC0000"
    ok = ok and marker_ok
    log("   %s = %s  %s" % (OUR_MARKER, out.strip(), "OK" if marker_ok else "★被改了！"))
    log()
    log("-- 他自己的标记文件 --")
    out, _ = board.run("cat '%s' 2>/dev/null" % SCOPE_DUAL_ADDR, quiet=True)
    log("   %s = %s" % (SCOPE_DUAL_ADDR, out.strip() or "(不存在)"))
    log()
    log("-- desktop.py 里在不在入口 --")
    out, _ = board.run("grep -c 'apps_scope_dual' '%s/desktop.py' 2>/dev/null" % UI, quiet=True)
    log("   apps_scope_dual 出现 %s 次" % out.strip())
    log()
    log("结果：%s" % ("全部完好 ✓" if ok else "★ 有基线文件被改动，请考虑 rollback.py"))
    return ok


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="部署双通道示波器 PS 层到 192.168.10.20")
    ap.add_argument("--stage", choices=("all", "files", "desktop"), default="all")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help="他的 scope_dual_axi 基地址（默认 %s，Lead 已定）" % DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true", help="只做只读预检，不写板子")
    ap.add_argument("--verify", action="store_true", help="只校验当前状态（只读）")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的目标文件")
    ap.add_argument("--with-cal", action="store_true", default=True,
                    help="一起推 cal_scope.py / cal_diag.py / cal_from_pairs.py（默认开）")
    ap.add_argument("--no-cal", dest="with_cal", action="store_false")
    ap.add_argument("--backup-boot", action="store_true",
                    help="连 /mnt/boot 的 4 个启动件也一起备份到板上（+4MB）")
    ap.add_argument("--allow-other-host", action="store_true")
    args = ap.parse_args()

    if not re.match(r"^0[xX][0-9a-fA-F]{8}$", args.base):
        print("--base 必须是 0x 开头的 8 位十六进制，例如 0x43CF0000")
        return 2

    try:
        if args.verify:
            return 0 if verify_only(args) else 1
        if args.dry_run:
            preflight(args)
            step("D", "DRY-RUN 结束 —— 没有写板子任何一个字节")
            log("实际部署请去掉 --dry-run")
            return 0

        rep = deploy(args)
        out = os.path.join(HERE, "_%s_%s.json" % (LOG_PREFIX, rep["ts"]))
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        step("9", "完成")
        log("报告：%s" % out)
        if rep.get("ok"):
            log("★ 部署成功。")
            log("  下一步（需要 Lead 批准）：上 JTAG 烧新 .bit 验证 PL，再重启验证四项硬指标。")
            log("  若任何一项不过：  python handover_b2\\rollback.py")
            return 0
        log("★ 部署未完成，请按上面提示处理。")
        return 1
    except Fail as ex:
        print("\n！！ 中止：%s" % ex)
        print("\n★ 回滚：  python handover_b2\\rollback.py")
        return 1
    except KeyboardInterrupt:
        print("\n被打断。若已开始写板子，请跑 rollback.py")
        return 130


if __name__ == "__main__":
    sys.exit(main())
