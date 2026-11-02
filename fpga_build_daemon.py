#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fpga_build_daemon.py —— FPGA 构建守护（PC 侧）

════════════════════════════════════════════════════════════════════
它在整个"agent 改 FPGA"闭环里的位置
════════════════════════════════════════════════════════════════════
板子上跑不动 Vivado（A9 + 1GB RAM），所以综合必须在 PC 上做。
但"发起构建"这个动作要能被**板子上的 agent** 触发 —— 这是这个项目的核心创新：
agent 能改自己的硬件。

于是约定用一个**文件队列**来解耦两端：

    板子 agent                                        PC（本脚本）
    ─────────                                        ────────────
    _vivado_build 写任务
        /home/zynq/fpga_jobs/<id>.request.json  ──►  轮询（走 SSH）
                                                         │
                                                     跑 Vivado
                                                     （HLS / 综合 / 实现 / 出流）
                                                         │
       ◄── 写结果 ──────────────────────────────  /home/zynq/fpga_jobs/<id>.result.json
    读结果、判断成败
        │
    _flash_bitstream 刷到板子
        │
    hw_verify 自动回归（不行就回滚）

★ 为什么用文件队列而不是 HTTP：
   · 板子在局域网里，PC 能 SSH 上去；反过来板子未必能连 PC（防火墙/IP 变动）
   · 文件天然持久：PC 挂了、板子重启了，任务都不会丢
   · 不需要在板子上开端口

════════════════════════════════════════════════════════════════════
任务文件格式
════════════════════════════════════════════════════════════════════
请求 <id>.request.json：
    {
      "id": "20261002_013000_1234",
      "ts": "2026-10-02 01:30:00",
      "kind": "hls" | "bitstream" | "synth_only",
      "desc": "给示波器加外部触发输入",
      "steps": [
        {"desc": "跑 HLS 综合 conv_pool", "cmd": "call v++ -c --mode hls ..."},
        ...
      ],
      "artifacts": ["work/conv_pool/cnn_conv_pool_q.zip"],   # 关心的产物
      "timeout_sec": 3600,
      "who": "zynq-agent"
    }

结果 <id>.result.json：
    {
      "id": ...,
      "status": "ok" | "failed" | "timeout",
      "ts": "...",
      "elapsed_sec": 812.3,
      "steps": [{"desc":..., "rc":0, "tail":"...", "elapsed":...}],
      "artifacts": [{"path":..., "size":..., "md5":..., "mtime":...}],
      "error": ""
    }

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    python fpga_build_daemon.py --once          # 处理一轮就退出（调试）
    python fpga_build_daemon.py                 # 常驻轮询
    python fpga_build_daemon.py --list          # 看有哪些任务
    python fpga_build_daemon.py --show <id>     # 看某个任务的结果
    python fpga_build_daemon.py --submit x.json # 本地提交一个任务（测试用）
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# 任务目录（在板子上，PC 通过 SSH 读写；也可以用本地目录测试）
#
# ★ 环境变量 FPGA_JOBS_DIR 可以覆盖 —— 板子侧的工具（agent/hw_tools.py）
#   也用同一个变量，这样两端能指到同一个目录，方便离线测整条链。
JOBS_REMOTE = os.environ.get("FPGA_JOBS_DIR", "/home/zynq/fpga_jobs")
JOBS_LOCAL = os.environ.get("FPGA_JOBS_DIR", os.path.join(HERE, "fpga_jobs"))

# Vivado
VIVADO = r"D:\Xilinx\2026.1\Vivado\bin\vivado.bat"
VITIS = r"D:\Xilinx\2026.1\Vitis\bin"
SETTINGS = r"D:\Xilinx\2026.1\Vivado\settings64.bat"

SSH_HELPER = os.path.join(HERE, "board.py")
POLL_SECS = 15


# ---------------------------------------------------------------- 板子交互
def board_run(cmd, timeout=300):
    """通过 board.py 在板子上跑一条命令"""
    p = subprocess.run([sys.executable, SSH_HELPER, cmd],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, cwd=HERE)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def board_read(path, timeout=120):
    """读板子上的一个文件（不存在返回 None）"""
    rc, out = board_run("cat %s 2>/dev/null || echo __NOFILE__" % path, timeout)
    if rc != 0 or "__NOFILE__" in out:
        return None
    # board.py 会在输出前面打一行 "[board] ..."，要剥掉
    lines = [ln for ln in out.split("\n")
             if not ln.startswith("[board]")]
    txt = "\n".join(lines).strip()
    if not txt or txt == "__NOFILE__":
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def board_write_json(path, obj, timeout=120):
    """把一个 JSON 写到板子上（走 base64，避免引号/中文出问题）

    ★★★ 权限兜底（实测踩过）：
      板子侧的任务可能是以 root 身份提交的（比如 sudo 跑演示脚本），
      那样 /home/zynq/fpga_jobs/ 就属 root，
      用普通 zynq 用户写 result.json 会 Permission denied ——
      于是任务永远"处理不完"，守护会反复重跑同一个任务。
      ⇒ 直接写失败就加 sudo 重试。
    """
    import base64
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
    b64 = base64.b64encode(data).decode()
    tmp = "/tmp/_jb64.txt"
    board_run("rm -f %s" % tmp, 30)
    CH = 3000
    for i in range(0, len(b64), CH):
        rc, out = board_run("printf '%%s' '%s' >> %s" % (b64[i:i + CH], tmp), 60)
        if rc != 0:
            return False, "写分块失败: %s" % out[:100]

    d = os.path.dirname(path)
    # 先试普通写
    rc, out = board_run(
        "mkdir -p %s 2>/dev/null; base64 -d %s > %s 2>/dev/null && rm -f %s "
        "&& echo OK" % (d, tmp, path, tmp), 60)
    if rc == 0 and "OK" in out:
        return True, out[:200]

    # ★ 失败就用 sudo（目录可能属 root）
    rc2, out2 = board_run(
        "sudo mkdir -p %s && sudo sh -c 'base64 -d %s > %s' && "
        "sudo rm -f %s && echo OK" % (d, tmp, path, tmp), 90)
    if rc2 == 0 and "OK" in out2:
        return True, "（用 sudo 写成功）" + out2[:120]
    return False, ("普通写失败: %s\n  sudo 也失败: %s"
                   % (out[:120], out2[:120]))


def board_list_jobs(timeout=60):
    rc, out = board_run(
        "ls -1 %s/*.request.json 2>/dev/null" % JOBS_REMOTE, timeout)
    if rc != 0:
        return []
    # ★ 已经有 result 的就不重复处理
    rc2, done = board_run(
        "ls -1 %s/*.result.json 2>/dev/null" % JOBS_REMOTE, timeout)
    done_ids = set()
    for ln in done.split("\n"):
        ln = ln.strip()
        if ln.endswith(".result.json"):
            done_ids.add(os.path.basename(ln)[:-len(".result.json")])
    ids = []
    for ln in out.split("\n"):
        ln = ln.strip()
        if ln.endswith(".request.json"):
            jid = os.path.basename(ln)[:-len(".request.json")]
            if jid not in done_ids:
                ids.append(jid)
    return ids


def board_upload(local, remote, timeout=600):
    p = subprocess.run([sys.executable, SSH_HELPER, "-p", local, remote],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, cwd=HERE)
    return p.returncode == 0


# ---------------------------------------------------------------- 本地执行
def md5_of(p):
    try:
        h = hashlib.md5()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        return h.hexdigest()
    except Exception:
        return None


def run_step(step, timeout):
    """跑一个构建步骤（在 PC 上）"""
    desc = step.get("desc", "?")
    cmd = step.get("cmd", "")
    cwd = step.get("cwd") or HERE
    t0 = time.time()
    print("   ▶ %s" % desc)
    print("     $ %s" % cmd[:160])
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        out = p.stdout.decode("utf-8", "replace")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out = "[超时 %d 秒]" % timeout
        rc = -1
    except Exception as e:
        out = "%s: %s" % (type(e).__name__, e)
        rc = -1
    dt = time.time() - t0
    tail = "\n".join(out.strip().split("\n")[-25:])
    print("     rc=%d  %.1fs" % (rc, dt))
    if tail:
        for ln in tail.split("\n"):
            print("       " + ln[:150])
    return {"desc": desc, "rc": rc, "elapsed": round(dt, 1), "tail": tail}


def handle_job(jid, req, verbose=True):
    """处理一个构建任务，返回结果 dict"""
    print("=" * 74)
    print(" 任务 %s: %s" % (jid, req.get("desc", "")))
    print(" kind=%s  steps=%d" % (req.get("kind"), len(req.get("steps", []))))
    print("=" * 74)

    t0 = time.time()
    results = []
    total_timeout = int(req.get("timeout_sec") or 3600)
    status = "ok"
    error = ""

    for step in req.get("steps", []):
        if time.time() - t0 > total_timeout:
            status = "timeout"
            error = "总超时 %d 秒已到" % total_timeout
            break
        r = run_step(step, max(60, total_timeout - int(time.time() - t0)))
        results.append(r)
        if r["rc"] != 0:
            status = "failed"
            error = "步骤失败: %s" % r["desc"]
            break

    # 收集产物信息
    arts = []
    for a in req.get("artifacts", []):
        p = a if os.path.isabs(a) else os.path.join(HERE, a)
        if os.path.exists(p):
            arts.append({"path": a, "size": os.path.getsize(p),
                         "md5": md5_of(p),
                         "mtime": datetime.datetime.fromtimestamp(
                             os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")})
        else:
            arts.append({"path": a, "missing": True})

    res = {
        "id": jid,
        "status": status,
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
        "steps": results,
        "artifacts": arts,
        "error": error,
    }
    print()
    print(" 结果: %s  用时 %.1f 秒" % (status, res["elapsed_sec"]))
    for a in arts:
        if a.get("missing"):
            print("   产物缺失: %s" % a["path"])
        else:
            print("   产物: %s  %d 字节  md5=%s"
                  % (a["path"], a["size"], a["md5"]))
    return res


def heartbeat(interval=None):
    """★★★ 写心跳文件（2026-10-03 加）

    为什么需要
    ────────────────────────────────────────────────────────────
    「守护进程到底在不在跑」是最容易出问题的一环（演示时忘了开），
    但检测它很麻烦：
      · wmic 在较新的 Windows 上【已经被移除】—— 我第一版检测用它，
        结果守护明明在跑（PID 10424），体检脚本却报"没在跑"。★踩过
      · psutil 不一定装了
    ⇒ 让守护自己写一个心跳文件，谁想知道就去看它，最可靠。

    文件：<HERE>/.fpga_daemon_heartbeat.json
    """
    try:
        d = {"pid": os.getpid(), "ts": time.time(),
             "iso": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "interval": interval}
        with open(os.path.join(HERE, ".fpga_daemon_heartbeat.json"), "w",
                  encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------- 主循环
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="处理一轮就退出")
    ap.add_argument("--list", action="store_true", help="列出待处理任务")
    ap.add_argument("--show", default="", help="看某个任务的结果")
    ap.add_argument("--submit", default="", help="提交一个任务文件（测试用）")
    ap.add_argument("--local", action="store_true",
                    help="用本地目录而不是板子（离线测试）")
    ap.add_argument("--interval", type=float, default=POLL_SECS)
    a = ap.parse_args()

    if a.local:
        global JOBS_REMOTE
        JOBS_REMOTE = JOBS_LOCAL
        os.makedirs(JOBS_LOCAL, exist_ok=True)

    # ---- 列出 ----
    if a.list:
        if a.local:
            ids = [os.path.basename(p)[:-len(".request.json")]
                   for p in glob.glob(os.path.join(JOBS_LOCAL, "*.request.json"))
                   if not os.path.exists(p.replace(".request.json", ".result.json"))]
        else:
            ids = board_list_jobs()
        if not ids:
            print("没有待处理的任务")
        for i in ids:
            print("  %s" % i)
        return 0

    # ---- 看结果 ----
    if a.show:
        if a.local:
            p = os.path.join(JOBS_LOCAL, a.show + ".result.json")
            if os.path.exists(p):
                print(open(p, encoding="utf-8").read())
            else:
                print("没有结果")
        else:
            r = board_read("%s/%s.result.json" % (JOBS_REMOTE, a.show))
            print(json.dumps(r, ensure_ascii=False, indent=1) if r else "没有结果")
        return 0

    # ---- 本地提交（测试用）----
    if a.submit:
        req = json.load(open(a.submit, encoding="utf-8"))
        jid = req.get("id") or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        req["id"] = jid
        os.makedirs(JOBS_LOCAL, exist_ok=True)
        res = handle_job(jid, req)
        with open(os.path.join(JOBS_LOCAL, jid + ".result.json"), "w",
                  encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("\n结果写到 %s/%s.result.json" % (JOBS_LOCAL, jid))
        return 0 if res["status"] == "ok" else 1

    # ---- 常驻轮询 ----
    print("=" * 74)
    print(" FPGA 构建守护")
    print("=" * 74)
    print(" 任务目录: %s%s" % (JOBS_REMOTE, "（本地模式）" if a.local else "（板子上）"))
    print(" Vivado:   %s" % VIVADO)
    ok = os.path.exists(VIVADO)
    print(" Vivado 在: %s" % ("✓" if ok else "✗ 找不到！"))
    if not ok:
        print("   ★ 改一下脚本顶部的 VIVADO 常量")
    print(" 轮询间隔: %.0f 秒" % a.interval)
    print()

    # ★★★ 心跳放【独立线程】（2026-10-03 修）
    #   原来是在主循环每轮写一次。但主循环跑到构建时会【阻塞】在
    #   subprocess.run 上（Vivado 一跑就是 25 分钟），心跳就停了
    #   —— 于是 fpga_loop_check 报"守护可能已经挂了"，纯属误报。
    #   （实测：跑构建时心跳停在 276 秒前，体检直接判 ✗）
    #   ⇒ 起一个后台线程定时写心跳，和构建并行。
    def _beat():
        while True:
            heartbeat(a.interval)
            time.sleep(max(5.0, min(30.0, a.interval)))
    threading.Thread(target=_beat, daemon=True).start()
    heartbeat(a.interval)              # 先立刻写一次，别等第一个周期

    while True:
        try:
            if a.local:
                ids = [os.path.basename(p)[:-len(".request.json")]
                       for p in glob.glob(os.path.join(JOBS_LOCAL, "*.request.json"))
                       if not os.path.exists(p.replace(".request.json", ".result.json"))]
            else:
                ids = board_list_jobs()

            if ids:
                print("[%s] 发现 %d 个任务: %s"
                      % (datetime.datetime.now().strftime("%H:%M:%S"),
                         len(ids), ", ".join(ids)))
                for jid in ids:
                    if a.local:
                        req = json.load(open(os.path.join(
                            JOBS_LOCAL, jid + ".request.json"), encoding="utf-8"))
                    else:
                        req = board_read("%s/%s.request.json" % (JOBS_REMOTE, jid))
                    if not req:
                        print("   ★ 读不到任务 %s，跳过" % jid)
                        continue
                    res = handle_job(jid, req)
                    if a.local:
                        with open(os.path.join(JOBS_LOCAL, jid + ".result.json"),
                                  "w", encoding="utf-8") as f:
                            json.dump(res, f, ensure_ascii=False, indent=1)
                    else:
                        okw, msg = board_write_json(
                            "%s/%s.result.json" % (JOBS_REMOTE, jid), res)
                        print("   结果写回板子: %s" % ("✓" if okw else "✗ " + msg))
            if a.once:
                return 0
            time.sleep(a.interval)
        except KeyboardInterrupt:
            print("\n退出")
            return 0
        except Exception as e:
            print("轮询出错: %s: %s" % (type(e).__name__, e))
            if a.once:
                return 1
            time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)
