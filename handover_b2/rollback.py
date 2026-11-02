#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rollback.py —— 一条命令把板子还原到 2026-10-14 的完好基线

基线（板端实测确认）
  zImage     fe8403e36d6c8bfde1d395d1d2b0c1f8   4,816,072 B
  system.dtb ece3cd8d656c7b26cd39ee8c8585d001      29,180 B
  system.bit 369b1a185ea656ce5cde9c4383d8b63a   4,045,769 B
  BOOT.BIN   949cc7c9c509133ff3e9541133220d58   4,933,576 B
  fbui.py       13ff672a762a28f4f3444fa6df2bf61f
  desktop.py    7d25f5b0f2f3dcbf2b6d2f4786350027
  apps_scope.py b2922c63664f150e8c3d2d85e3b738a3
  scope.py      dc27fd691cf058d2c11ad52b07fac86c
  libscope.so   c412125e35bf9e06d07bad262b13e84c
  /home/zynq/.scope_addr = 0x43CC0000

设计原则
  1. ★ 带 md5 校验：删/恢复之后逐个校验；恢复后的文件 md5 必须等于基线值。
  2. ★ 时间戳备份：回滚【也会】先备份当前状态到 `_b2_rollback_backup_<TS>/`，
     所以「回滚」这个动作本身也是可逆的。
  3. ★ 失败自动停止：任何一步不符立刻停，绝不继续往下删。
  4. ★ 白名单删除：只删 deploy_ps.py 明确新增的那些文件。
     任何不在白名单里的文件，哪怕它看起来像是新增的，也【绝不删】。

用法
  python rollback.py                 # 回滚到最近一次部署之前的备份
  python rollback.py --list          # 列出板上所有备份（只读）
  python rollback.py --to 20261015_143001   # 指定某一时刻的备份
  python rollback.py --check         # 只校验当前状态，不写板子
  python rollback.py --dry-run       # 打印将要做的每一件事，不写板子
  python rollback.py --keep-new      # 只还原被改的文件，不删新增文件
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
UBUNTU = os.path.dirname(HERE)

sys.path.insert(0, UBUNTU)
try:
    import board                                            # noqa: E402
except Exception as ex:                                     # pragma: no cover
    print("！！ 无法 import board.py（%s）。请在 D:\\ubuntu_iso 下跑。" % ex)
    sys.exit(2)

UI = "/home/zynq/ui"
BACKUP_GLOB = "/home/zynq/ui/_b2_backup_*"
RB_GLOB = "/home/zynq/ui/_b2_rollback_backup_*"
OUR_MARKER = "/home/zynq/.scope_addr"
SCOPE_DUAL_ADDR = "/home/zynq/.scope_dual_addr"

BOOT_BASELINE = {
    "/mnt/boot/system.bit": "369b1a185ea656ce5cde9c4383d8b63a",
    "/mnt/boot/system.dtb": "ece3cd8d656c7b26cd39ee8c8585d001",
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
ALL_BASELINE = dict(UI_BASELINE)
ALL_BASELINE.update(BOOT_BASELINE)

# ★ 只有这些可以删（deploy_ps.py 新增的）
DELETE_WHITELIST = {
    UI + "/scope_dual.py",
    UI + "/scope_processing.py",
    UI + "/scope_model.py",
    UI + "/apps_scope_dual.py",
    UI + "/scope_dual.c",
    UI + "/libscopedual.so",
    UI + "/cal_scope.py",
    UI + "/cal_diag.py",
    UI + "/cal_from_pairs.py",
    SCOPE_DUAL_ADDR,
}
# 双保险：白名单和基线集合绝不能有交集
assert not (DELETE_WHITELIST & set(ALL_BASELINE)), "白名单和基线集重叠了，代码有 bug"
assert OUR_MARKER not in DELETE_WHITELIST, "绝不允许删我们的基址标记文件"

_RC_MARK = "__B2_RC__"


class Fail(Exception):
    pass


def log(m=""):
    print(m, flush=True)


def step(n, title):
    log()
    log("=" * 74)
    log(" 步骤 %s  %s" % (n, title))
    log("=" * 74)


def sh_rc(cmd, timeout=300):
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


def sh(cmd, timeout=300, check=True):
    rc, out, err = sh_rc(cmd, timeout=timeout)
    if check and rc != 0:
        raise Fail("板上命令失败 rc=%s\n  cmd: %s\n  out: %s\n  err: %s"
                   % (rc, cmd, out.strip()[-600:], err.strip()[-600:]))
    return out, err


def r_md5(path):
    out, _ = board.run("md5sum '%s' 2>/dev/null" % path, quiet=True)
    parts = out.strip().split()
    return parts[0] if parts and len(parts[0]) == 32 else None


def r_exists(path):
    out, _ = board.run("[ -e '%s' ] && echo YES || echo NO" % path, quiet=True)
    return out.strip().endswith("YES")


def md5_text(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ 列备份
def list_backups():
    out, _ = board.run("ls -1d %s 2>/dev/null; echo ---; ls -1d %s 2>/dev/null"
                       % (BACKUP_GLOB, RB_GLOB), quiet=True)
    parts = out.split("---")
    dep = [x.strip() for x in parts[0].splitlines() if x.strip()]
    rb = [x.strip() for x in parts[1].splitlines() if x.strip()] if len(parts) > 1 else []
    return sorted(dep), sorted(rb)


def read_manifest(bdir):
    txt, _ = board.run("cat '%s/manifest.json' 2>/dev/null" % bdir, quiet=True)
    if not txt.strip():
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


# ------------------------------------------------------------------ 只读校验
def check_only():
    step("C", "只读校验（不写板子）")
    ok = True
    log("-- 基线文件 --")
    for p, want in ALL_BASELINE.items():
        got = r_md5(p)
        same = (got == want)
        ok = ok and same
        log("   %-34s %s  %s" % (p, got or "(读不到)", "OK" if same else "★不符(期望 %s)" % want))
    log()
    log("-- 我们的基址标记（红线）--")
    out, _ = board.run("cat '%s' 2>/dev/null" % OUR_MARKER, quiet=True)
    m_ok = out.strip() == "0x43CC0000"
    ok = ok and m_ok
    log("   %s = %s  %s" % (OUR_MARKER, out.strip() or "(空)", "OK" if m_ok else "★被改了"))
    log()
    log("-- 新增文件（回滚会删这些）--")
    for p in sorted(DELETE_WHITELIST):
        log("   %-44s %s" % (p, r_md5(p) or "不存在"))
    log()
    log("-- 判定 --")
    if ok:
        log("   ✓ 已经在完好基线上，不需要回滚")
    else:
        log("   ★ 有文件偏离基线 ⇒ 需要回滚：  python rollback.py")
    return ok


# ------------------------------------------------------------------ 回滚主体
def rollback(args):
    TS = time.strftime("%Y%m%d_%H%M%S")
    report = {"ts": TS, "host": board.HOST, "ok": False}

    step("0", "找到要用的备份")
    deps, rbs = list_backups()
    log("部署备份 (_b2_backup_*)      : %d 个" % len(deps))
    for d in deps[-5:]:
        log("   " + d)
    log("回滚备份 (_b2_rollback_backup_*) : %d 个" % len(rbs))
    for d in rbs[-5:]:
        log("   " + d)

    if args.to:
        cand = [d for d in deps if args.to in d]
        if not cand:
            raise Fail("找不到匹配 --to %s 的备份" % args.to)
        bdir = cand[-1]
    else:
        if not deps:
            raise Fail("板上没有任何 _b2_backup_* 备份。\n"
                       "  ⇒ 说明还没跑过 deploy_ps.py，或者备份被删了。\n"
                       "  ⇒ 如果只是想把文件还原成基线，可以用 PC 上的 "
                       "_baseline\\20261014\\board_boot\\ 手工恢复；\n"
                       "     但 /home/zynq/ui 的 5 个基线文件请从 "
                       "handover\\board_ui\\ 推回去（md5 已核对一致）。")
        bdir = deps[-1]
    log()
    log("选用备份：%s" % bdir)

    man = read_manifest(bdir)
    if man:
        log("manifest.json 读取 OK（部署时间 %s）" % man.get("ts"))
    else:
        log("⚠ 没有 manifest.json —— 退化为「按已知文件名恢复」模式")

    # 判断每个基线文件在备份里的位置（manifest 优先，否则按 basename 猜）
    def bak_path(orig):
        if man:
            for it in man.get("items", []):
                if it.get("orig") == orig:
                    return it.get("bak")
        return posixpath.join(bdir, os.path.basename(orig))

    # ---------------------------------------------------------- 1. 备份当前状态
    step("1", "先备份【当前】状态（让回滚本身也可逆）")
    now_rb = "%s/_b2_rollback_backup_%s" % (UI, TS)
    if args.dry_run:
        log("   [dry-run] mkdir -p %s" % now_rb)
    else:
        sh("mkdir -p '%s'" % now_rb)
    for p in list(ALL_BASELINE) + [OUR_MARKER] + sorted(DELETE_WHITELIST):
        if not r_exists(p):
            log("   %-44s 不存在，跳过" % p)
            continue
        if args.dry_run:
            log("   [dry-run] cp -p %s -> %s/" % (p, now_rb))
        else:
            sh("cp -p '%s' '%s/' 2>/dev/null || true" % (p, now_rb))
            log("   %-44s 已备份" % p)
    report["rollback_backup_dir"] = now_rb

    # ---------------------------------------------------------- 2. 恢复被改的文件
    step("2", "从备份恢复基线文件（恢复后逐个 md5 校验）")
    for orig, want in ALL_BASELINE.items():
        src = bak_path(orig)
        if not r_exists(src):
            raise Fail("备份里没有 %s（找的是 %s）—— 中止，别把文件搞丢" % (orig, src))
        # 先确认备份里的 md5 就是基线值（防止备份本身是坏的）
        bmd5 = r_md5(src)
        if bmd5 != want:
            raise Fail("备份里的 %s md5=%s，不是基线的 %s —— 备份不可信，中止"
                       % (src, bmd5, want))
        if args.dry_run:
            log("   [dry-run] cp -f %s -> %s" % (src, orig))
            continue
        sh("cp -f '%s' '%s'" % (src, orig))
        got = r_md5(orig)
        if got != want:
            raise Fail("恢复后 %s 的 md5=%s != 基线 %s" % (orig, got, want))
        log("   %-34s OK  md5=%s" % (orig, got))
    report["steps"] = ["baseline files restored"]

    # ---------------------------------------------------------- 3. 还原我们的标记
    step("3", "还原我们的基址标记（红线文件）")
    out, _ = board.run("cat '%s' 2>/dev/null" % OUR_MARKER, quiet=True)
    if out.strip() == "0x43CC0000":
        log("   %s 已经是 0x43CC0000，不动" % OUR_MARKER)
    else:
        if args.dry_run:
            log("   [dry-run] 写回 0x43CC0000")
        else:
            sh("printf '0x43CC0000\\n' > '%s'" % OUR_MARKER)
            chk, _ = board.run("cat '%s'" % OUR_MARKER, quiet=True)
            if chk.strip() != "0x43CC0000":
                raise Fail("标记文件还原失败：%s" % chk.strip())
            log("   %s 已还原为 0x43CC0000" % OUR_MARKER)

    # ---------------------------------------------------------- 4. 删掉新增文件
    if args.keep_new:
        step("4", "跳过删除新增文件（--keep-new）")
    else:
        step("4", "删除【白名单内】的新增文件（别的一律不删）")
        for p in sorted(DELETE_WHITELIST):
            if p in ALL_BASELINE:
                raise Fail("内部错误：白名单里有基线文件 %s —— 拒绝继续" % p)
            if not r_exists(p):
                log("   %-44s 不存在，跳过" % p)
                continue
            if args.dry_run:
                log("   [dry-run] rm -f %s" % p)
                continue
            sh("rm -f '%s'" % p)
            if r_exists(p):
                raise Fail("删除失败：%s" % p)
            log("   %-44s 已删除" % p)
        # 顺手清掉这些模块的 pyc（否则 import 可能命中旧缓存）
        if not args.dry_run:
            sh("rm -f '%s/__pycache__'/scope_dual.* '%s/__pycache__'/scope_model.* "
               "'%s/__pycache__'/scope_processing.* '%s/__pycache__'/apps_scope_dual.* "
               "'%s/__pycache__'/desktop.* 2>/dev/null || true" % (UI, UI, UI, UI, UI))
        report["steps"].append("new files removed")

    # ---------------------------------------------------------- 5. 最终校验
    step("5", "最终校验（必须全部回到基线）")
    bad = []
    for p, want in ALL_BASELINE.items():
        got = r_md5(p)
        same = (got == want)
        if not same:
            bad.append("%s (实际 %s, 期望 %s)" % (p, got, want))
        log("   %-34s %s" % (p, "OK" if same else "★不符 %s" % (got or "(读不到)")))

    log()
    log("-- 新增文件必须都没了 --")
    left = [p for p in sorted(DELETE_WHITELIST) if r_exists(p)]
    for p in sorted(DELETE_WHITELIST):
        log("   %-44s %s" % (p, "★还在" if p in left else "已清除"))
    if left and not args.keep_new:
        bad.extend(["残留: " + x for x in left])

    log()
    log("-- desktop.py 里不该再有入口 --")
    out, _ = board.run("grep -c 'apps_scope_dual' '%s/desktop.py' 2>/dev/null" % UI, quiet=True)
    n = out.strip() or "0"
    log("   apps_scope_dual 出现 %s 次（应为 0）" % n)
    if n not in ("0", ""):
        bad.append("desktop.py 里还残留 apps_scope_dual 引用")

    log()
    log("-- 我们的基线文件 md5 汇总 --")
    for p, want in UI_BASELINE.items():
        log("   %-30s %s" % (os.path.basename(p), r_md5(p)))

    if bad:
        log()
        log("!" * 74)
        log("！！ 回滚【未完成】，还有问题：")
        for x in bad:
            log("   - %s" % x)
        log("!" * 74)
        report["problems"] = bad
        return report

    log()
    log("★ 回滚完成：所有基线文件 md5 一致，新增文件已清除。")
    log("  建议重启一次并复核四项硬指标：")
    log("    □ 能正常启动（不 panic / 不黑屏）")
    log("    □ /sys/class/graphics/fb0/modes 含 U:1024x600p-0")
    log("    □ ls /sys/bus/i2c/devices/ 含 2-0014 与 2-0038")
    log("    □ /sys/class/input/event1/device/name = Goodix Capacitive TouchScreen")
    log("    □ /proc/asound/cards 含 xlnx-i2s-snd-card-0；systemctl is-active zynq-audio")
    log("      -> active")
    log("    □ 原示波器（apps_scope）能打开")
    report["ok"] = True
    return report


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="把板子还原到 2026-10-14 完好基线")
    ap.add_argument("--list", action="store_true", help="列出板上所有备份（只读）")
    ap.add_argument("--check", action="store_true", help="只校验当前状态（只读）")
    ap.add_argument("--to", default="", help="指定备份时间戳片段，例如 20261015_1430")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做什么，不写板子")
    ap.add_argument("--keep-new", action="store_true", help="只还原被改文件，不删新增文件")
    args = ap.parse_args()

    try:
        if not board.HOST:
            raise Fail("找不到板子。请设置 $env:BOARD_IP=\"192.168.10.20\"。")
        if board.HOST != "192.168.10.20":
            log("⚠ 目标不是我们板子（192.168.10.20），而是 %s —— 请确认！" % board.HOST)

        if args.list:
            step("L", "板上备份列表（只读）")
            deps, rbs = list_backups()
            log("部署前备份：")
            for d in deps:
                m = read_manifest(d)
                log("   %s   %s" % (d, ("manifest ts=%s" % m.get("ts")) if m else "(无 manifest)"))
            log("回滚前备份：")
            for d in rbs:
                log("   " + d)
            return 0

        if args.check:
            return 0 if check_only() else 1

        rep = rollback(args)
        out = os.path.join(HERE, "_rollback_%s.json" % rep["ts"])
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        step("9", "完成")
        log("报告：%s" % out)
        return 0 if rep.get("ok") else 1

    except Fail as ex:
        print("\n！！ 回滚中止：%s" % ex)
        print("\n板上有一份回滚前备份（_b2_rollback_backup_*），可以手工继续。")
        return 1
    except KeyboardInterrupt:
        print("\n被打断。请重新跑 rollback.py（它本身是幂等的）。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
