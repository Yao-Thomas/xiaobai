#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_change.py —— 变更管理：变更单 + 自动验证 + 自动回滚

════════════════════════════════════════════════════════════════════
为什么需要它
════════════════════════════════════════════════════════════════════
这个项目的核心主张是"Agent 能改自己的硬件"。但"能改"和"敢让它改"是两回事。

真正让这件事可信的，不是让模型更聪明，而是把流程做成**不可能悄悄改坏**：

    改之前 → 记变更单（谁、什么时候、改什么、为什么）
    改之前 → 快照（涉及的文件全部备份，能原样恢复）
    改完   → **自动跑验证清单**（不是人肉点一遍，是脚本跑）
    验证过 → 保留，变更单标记"已验证"
    验证挂 → **自动回滚**，变更单标记"已回滚"，把失败原因留给模型看

关键在最后两条：**验证和回滚都是自动的**。这样模型改错了也不会把板子
留在坏状态 —— 它只会得到一条"你改错了，已经回滚，原因是 XXX"。

════════════════════════════════════════════════════════════════════
验证清单（就是回归检查那套）
════════════════════════════════════════════════════════════════════
    ① 桌面起来了         （zynq-desktop active）
    ② 音频服务在          （zynq-audio active）
    ③ agent 在            （zynq-agent active + HTTP /health）
    ④ 自研 IP 在线        （scope_0 / gpu_0 的 VERSION 寄存器）
    ⑤ CNN 地址可读        （0x43CD0000 / 0x43CE0000 不 SIGBUS）
    ⑥ 音频 codec 在       （ES8388 寄存器能读）
    ⑦ 帧缓冲正常          （1024x1200 / 24bpp）
    ⑧ 温度没爆表          （< EMERG）

★ ⑥⑦⑧ 是"软"检查（失败只警告），①②③④⑤ 是"硬"检查（失败就回滚）。

════════════════════════════════════════════════════════════════════
用法（作为库被 hw_tools 调用，也可以命令行单独跑）
════════════════════════════════════════════════════════════════════
    sudo python3 hw_change.py --verify            # 只跑验证清单
    sudo python3 hw_change.py --list              # 列变更单
    sudo python3 hw_change.py --rollback <id>     # 回滚某一条
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHANGE_DIR = "/var/lib/hwchange"
CHANGE_FILE = CHANGE_DIR + "/changes.jsonl"
SNAPSHOT_DIR = CHANGE_DIR + "/snapshots"

PL_MAP = {
    "scope_0": (0x43CC0000, 0x34, 0x53434F50),
    # ★★★ 2026-10-03 由 agent 同步更新（"agent 改 FPGA"闭环的最后一环）
    #
    # 这个期望值原来是 0xDEADBEEF —— gpu2d_axi.v 里 default 分支的返回值。
    # agent 把它改成了 0x47505532（ASCII "GPU2"）并重新出流、刷板，
    # 于是 hw_verify 立刻报：
    #     [硬] ✗ gpu_0 在线   0x47505532（期望 0xDEADBEEF）
    #     ★ 结论：硬检查有失败 —— 需要用 hw_change_rollback 回滚
    #
    # ★ 这里【没有】回滚，而是更新期望值 —— 因为硬件规格确实变了，
    #   该跟着变的是验证清单，不是硬件。这正是闭环里最容易漏的一步：
    #   改了硬件却没改验证，下次跑检查就会误判成"坏了"。
    #   （反过来也说明检查是有效的：它真的发现了不一致。）
    #
    # ★ 改这里必须和 HDL 里的值【成对】改：
    #     atk2026/.../ipshared/eaea/src/gpu2d_axi.v 的 default 分支
    "gpu_0": (0x43CB0000, 0x34, 0x47505532),
}
CNN_ADDRS = [0x43CD0000, 0x43CE0000]


def sh(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace")
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


# ══════════════════════════════════════════════════════════════════
#  ★★★ /dev/mem 权限探测（2026-10-03 修）
# ══════════════════════════════════════════════════════════════════
# 踩过的坑（很隐蔽）：
#   hw_verify 一直报「scope_0 在线 ✗ 读不到」「CNN ✗ SIGBUS」，
#   看着像 PL 里根本没有这些 IP —— 其实硬件完全正常：
#       root 身份读 0x43CB0034 -> 0xDEADBEEF   ✓
#       zynq 身份读同一地址    -> SIGBUS        ✗
#   根因：/dev/mem 是 root:kmem 0640，而 agent 以 zynq 用户跑，
#   而 read_pl 是 sh(["python3","-c",code]) —— 继承了 agent 的身份。
#
#   ⇒ 先探测当前进程能不能开 /dev/mem，不能就用 sudo -n 提权。
#     （zynq 在这块板子上有免密 sudo；万一没有，会自然退化成失败。）
# ══════════════════════════════════════════════════════════════════
_DEVMEM_OK = None


def can_read_devmem():
    """当前进程能不能直接打开 /dev/mem（结果缓存，只探一次）"""
    global _DEVMEM_OK
    if _DEVMEM_OK is None:
        try:
            fd = os.open("/dev/mem", os.O_RDONLY)
            os.close(fd)
            _DEVMEM_OK = True
        except Exception:
            _DEVMEM_OK = False
    return _DEVMEM_OK


def read_pl(base, off, timeout=8):
    """★ 必须 fork 子进程读 —— 读没映射的地址会 SIGBUS 打死本进程

    ★ /dev/mem 通常只有 root 能开（root:kmem 0640），
      所以权限不够时自动走 sudo -n。
    """
    code = (
        "import mmap,os,struct,sys\n"
        "try:\n"
        "    fd=os.open('/dev/mem', os.O_RDONLY|os.O_SYNC)\n"
        "    m=mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=%d)\n"
        "    print(struct.unpack_from('<I', m, %d)[0])\n"
        "except Exception as e:\n"
        "    sys.exit(1)\n" % (base, off))
    cmd = ["python3", "-c", code]
    if not can_read_devmem():
        cmd = ["sudo", "-n"] + cmd
    rc, out = sh(cmd, timeout)
    if rc != 0:
        return None
    try:
        return int(out.strip())
    except Exception:
        return None


def svc(name):
    rc, out = sh(["systemctl", "is-active", name], 10)
    return out.strip()


def file_md5(p):
    try:
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def read_temp():
    try:
        raw = int(open("/sys/bus/iio/devices/iio:device0/in_temp0_raw").read())
        sc = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_scale").read())
        of = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_offset").read())
        return (raw + of) * sc / 1000.0
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  验证清单
# ══════════════════════════════════════════════════════════════════
def verify_all(verbose=True):
    """跑一遍回归清单，返回 (是否通过, 详细列表)

    硬检查失败 -> 不通过（触发回滚）
    软检查失败 -> 只警告
    """
    checks = []

    def add(name, ok, hard, detail=""):
        checks.append({"name": name, "ok": bool(ok),
                       "hard": hard, "detail": detail})

    # ① 服务
    for svc_name, label in (("zynq-desktop", "桌面"),
                            ("zynq-audio", "音频服务"),
                            ("zynq-agent", "Agent")):
        st = svc(svc_name)
        add("%s 在跑" % label, st == "active", True, st)

    # ② agent HTTP
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=6) as r:
            body = r.read().decode()
        add("Agent HTTP 响应", r.status == 200, True, body[:60])
    except Exception as e:
        add("Agent HTTP 响应", False, True, str(e)[:60])

    # ③ 自研 IP 在线（VERSION 寄存器）
    for ip, (base, off, want) in PL_MAP.items():
        v = read_pl(base, off)
        got = ("0x%08X" % v) if v is not None else "读不到"
        add("%s 在线" % ip, v == want, True,
            "%s（期望 0x%08X）" % (got, want))

    # ④ CNN 地址可读（不 SIGBUS）
    for base in CNN_ADDRS:
        v = read_pl(base, 0x00)
        add("CNN @0x%08X 可读" % base, v is not None, True,
            ("0x%08X" % v) if v is not None else "SIGBUS/读不到")

    # ⑤ 音频 codec（软）
    # ★ /dev/i2c-1 是 root:i2c 0660，zynq 不在 i2c 组里 —— 同样要 sudo。
    #   （和 read_pl 一个道理；不修的话这条永远报 "Could not open"）
    def _i2cget():
        cmd = ["i2cget", "-f", "-y", "1", "0x10", "0x00"]
        rc, out = sh(cmd, 10)
        if rc != 0 or not out.strip().startswith("0x"):
            rc2, out2 = sh(["sudo", "-n"] + cmd, 10)
            if rc2 == 0 and out2.strip().startswith("0x"):
                return rc2, out2
        return rc, out
    rc, out = _i2cget()
    add("ES8388 可读", rc == 0 and out.strip().startswith("0x"), False,
        out.strip()[:20])

    # ⑥ 帧缓冲（软）
    try:
        vs = open("/sys/class/graphics/fb0/virtual_size").read().strip()
        bpp = open("/sys/class/graphics/fb0/bits_per_pixel").read().strip()
        add("帧缓冲正常", vs == "1024,1200" and bpp == "24", False,
            "%s / %s" % (vs, bpp))
    except Exception as e:
        add("帧缓冲正常", False, False, str(e)[:40])

    # ⑦ 温度（软）
    t = read_temp()
    add("温度未爆表", (t is not None and t < 96.0), False,
        ("%.1f°C" % t) if t is not None else "读不到")

    hard_fail = [c for c in checks if c["hard"] and not c["ok"]]
    soft_fail = [c for c in checks if not c["hard"] and not c["ok"]]

    if verbose:
        print("=" * 70)
        print(" 变更后验证清单")
        print("=" * 70)
        for c in checks:
            tag = "硬" if c["hard"] else "软"
            mark = "✓" if c["ok"] else ("✗" if c["hard"] else "⚠")
            print("  [%s] %s %-22s %s" % (tag, mark, c["name"], c["detail"]))
        print()
        if hard_fail:
            print(" ★ 硬检查失败 %d 项 -> 需要回滚" % len(hard_fail))
        elif soft_fail:
            print(" 硬检查全过，软检查有 %d 项警告" % len(soft_fail))
        else:
            print(" ★ 全部通过")
    return (len(hard_fail) == 0), checks


# ══════════════════════════════════════════════════════════════════
#  变更单
# ══════════════════════════════════════════════════════════════════
def _new_id():
    return time.strftime("%Y%m%d_%H%M%S") + "_%04d" % (int(time.time() * 997) % 10000)


def change_add(kind, detail, result="", who="agent", cid=None, extra=None):
    """记一条变更单，返回 id"""
    cid = cid or _new_id()
    rec = {
        "id": cid,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "detail": detail,
        "result": result,
        "who": who,
    }
    if extra:
        rec.update(extra)
    try:
        os.makedirs(CHANGE_DIR, exist_ok=True)
        with open(CHANGE_FILE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return cid


def change_list(limit=10):
    if not os.path.exists(CHANGE_FILE):
        return []
    out = []
    try:
        for ln in open(CHANGE_FILE).read().splitlines()[-limit:]:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    except Exception:
        pass
    return out


# ══════════════════════════════════════════════════════════════════
#  快照 / 回滚
# ══════════════════════════════════════════════════════════════════
def snapshot(cid, paths):
    """把一组文件复制到快照目录，返回清单（含 md5）"""
    d = os.path.join(SNAPSHOT_DIR, cid)
    manifest = []
    try:
        os.makedirs(d, exist_ok=True)
        for p in paths:
            if not os.path.exists(p):
                manifest.append({"path": p, "existed": False})
                continue
            base = os.path.basename(p)
            dst = os.path.join(d, base)
            shutil.copy2(p, dst)
            manifest.append({"path": p, "existed": True,
                             "snap": dst, "md5": file_md5(p)})
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        return manifest
    except Exception as e:
        return [{"error": str(e)}]


def rollback(cid, verbose=True):
    """把某次变更涉及的文件恢复回去

    ★★★ 2026-10-02 加：没有快照时，回退到【变更单里记的备份文件】。
      为什么需要：hw_tools 的 hw_hdl_edit 走的是"改一个文件 + 留 .bak"的路子，
      不一定会建快照。以前遇到这种情况直接报"找不到快照"，
      明明有备份却回滚不了（离线测试抓出来的）。
      现在两条路都支持：优先快照（能恢复多个文件），没快照就用备份。
    """
    d = os.path.join(SNAPSHOT_DIR, cid)
    mf = os.path.join(d, "manifest.json")

    if not os.path.exists(mf):
        # ---- 兜底：用变更单里记的备份 ----
        rec = None
        for r in change_list(10000):
            if r.get("id") == cid:
                rec = r
                break
        if not rec:
            return False, "找不到变更单 %s（也没快照）" % cid
        bak = rec.get("backup")
        path = rec.get("path")
        if not bak or not path:
            return False, ("变更单 %s 里没记备份路径，也没快照 —— 无法回滚" % cid)
        if not os.path.exists(bak):
            return False, "备份文件不存在了：%s" % bak
        try:
            shutil.copy2(bak, path)
        except Exception as e:
            return False, "用备份恢复失败: %s" % e
        if verbose:
            print("   ✓ 用备份恢复 %s" % path)
            print("     （备份来自 %s）" % bak)
        change_add("rollback", "回滚 %s（用备份）" % cid, "成功")
        return True, "用备份恢复 %s" % path

    try:
        manifest = json.load(open(mf, encoding="utf-8"))
    except Exception as e:
        return False, "快照清单坏了: %s" % e

    done, failed = [], []
    for item in manifest:
        if "error" in item:
            continue
        p = item["path"]
        if not item.get("existed"):
            # 原来不存在 -> 删掉现在这个
            try:
                if os.path.exists(p):
                    os.remove(p)
                done.append("删除 %s（原来没有）" % p)
            except Exception as e:
                failed.append("%s: %s" % (p, e))
            continue
        snap = item.get("snap")
        try:
            if os.path.exists(snap):
                shutil.copy2(snap, p)
                done.append("恢复 %s" % p)
            else:
                failed.append("%s: 快照文件丢了" % p)
        except Exception as e:
            failed.append("%s: %s" % (p, e))

    if verbose:
        for x in done:
            print("   ✓ " + x)
        for x in failed:
            print("   ✗ " + x)
    return (len(failed) == 0), "; ".join(failed) if failed else "全部恢复"


def apply_change(kind, detail, actions, paths=(), who="agent",
                 skip_verify=False, verbose=True):
    """★ 核心：应用一次变更，自动验证，失败自动回滚

    actions: [(描述, 命令), ...]  按顺序执行
    paths:   涉及的文件（用于快照/回滚）

    返回 (成功?, 说明)
    """
    cid = change_add(kind, detail, "进行中", who)
    if verbose:
        print("=" * 70)
        print(" 变更 %s: %s" % (cid, detail))
        print("=" * 70)

    # 1) 快照
    manifest = snapshot(cid, list(paths))
    if any("error" in m for m in manifest):
        change_add(kind, detail, "快照失败，中止", who, cid)
        return False, "★ 快照失败，为安全起见中止（没有动任何东西）"
    if verbose and paths:
        print(" 已快照 %d 个文件" % len(paths))

    # 2) 执行
    logs = []
    for desc, cmd in actions:
        if verbose:
            print(" 执行: %s" % desc)
        rc, out = sh(cmd, 600)
        logs.append({"desc": desc, "rc": rc, "out": out[-500:]})
        if verbose:
            print("   -> rc=%d %s" % (rc, out.strip()[:200]))
        if rc != 0:
            # 执行失败 -> 回滚
            if verbose:
                print(" ★ 执行失败，回滚")
            ok, why = rollback(cid, verbose)
            change_add(kind, detail, "执行失败已回滚: %s" % desc, who, cid,
                       {"logs": logs, "rollback_ok": ok, "rollback": why})
            return False, ("★ 变更执行失败（%s），已%s回滚。\n原因: %s"
                           % (desc, "" if ok else "尝试", out.strip()[:300]))

    # 3) 验证
    if skip_verify:
        change_add(kind, detail, "已应用（跳过验证）", who, cid, {"logs": logs})
        return True, "变更已应用（★ 跳过了自动验证，风险自负）"

    if verbose:
        print()
    passed, checks = verify_all(verbose)

    # 4) 结果
    if passed:
        change_add(kind, detail, "已应用且验证通过", who, cid,
                   {"logs": logs, "checks": checks})
        return True, "★ 变更已应用，自动验证通过（%d 项检查）" % len(checks)

    bad = [c["name"] for c in checks if c["hard"] and not c["ok"]]
    if verbose:
        print(" ★ 验证不通过（%s），回滚" % ", ".join(bad))
    ok, why = rollback(cid, verbose)
    change_add(kind, detail, "验证失败已回滚", who, cid,
               {"logs": logs, "checks": checks,
                "failed": bad, "rollback_ok": ok, "rollback": why})
    return False, ("★ 变更后验证不通过（%s），已%s回滚。\n"
                   "  ⇒ 这个改动不可用，换思路。"
                   % (", ".join(bad), "" if ok else "尝试"))


# ---------------------------------------------------------------- CLI
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="只跑验证清单")
    ap.add_argument("--list", action="store_true", help="列变更单")
    ap.add_argument("--rollback", default="", help="回滚指定 id")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()

    if a.verify:
        ok, _ = verify_all()
        return 0 if ok else 1

    if a.list:
        recs = change_list(a.limit)
        if not recs:
            print("还没有变更单")
            return 0
        for r in recs:
            print("[%s] %-12s %s" % (r.get("id"), r.get("kind"),
                                     r.get("detail")))
            print("         时间 %s  结果 %s  by %s"
                  % (r.get("ts"), r.get("result"), r.get("who")))
        return 0

    if a.rollback:
        ok, why = rollback(a.rollback)
        print("回滚 %s: %s" % ("成功" if ok else "失败", why))
        return 0 if ok else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
