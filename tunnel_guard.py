#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tunnel_guard.py —— 手机入口看门狗

════════════════════════════════════════════════════════════════════
为什么需要它
════════════════════════════════════════════════════════════════════
手机通过 cloudflared 隧道连电脑上的 DSH。但实测发现：
    · 隧道会自己断（cloudflared 进程消失）—— 今天就是这样，
      用户在外面打不开才发现
    · 快速隧道的网址重启就变 —— 变了以后旧网址永久失效
    · 代理（dsh_proxy，3081）也可能挂

人不在电脑前的时候，这些都得自动恢复，而且**得让用户知道新网址**。

════════════════════════════════════════════════════════════════════
它做四件事
════════════════════════════════════════════════════════════════════
    ① 盯着代理（3081）在不在，不在就拉起来
    ② 盯着 cloudflared 在不在，不在就拉起来
    ③ 网址变了 —— 推微信通知新网址
    ④ 每 5 分钟自检一次：从公网真的能打开吗（带口令请求一下）

★ 只在"状态变化"时推微信，避免刷屏。

用法:
    python tunnel_guard.py                # 前台跑
    python tunnel_guard.py --once         # 检查一轮就退出（调试）
    python tunnel_guard.py --status       # 只看状态
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CF = os.path.join(HERE, "cloudflared.exe")
# ★★★ LOG 修（2026-10-03）：
#   原来这里读的是 tunnel.err，而 tunnel.py 写的是 tunnel.log
#   —— 两个文件对不上，于是看门狗一直读到【24 小时前的旧网址】
#   （tunnel.err 是 10/02 的遗留文件，里面是 sox-aggregate-…）。
#   后果很实际：隧道断了自动重连后，推给用户的会是打不开的旧地址。
#   ⇒ 统一用 tunnel.log；同时把 tunnel.err 当兜底（兼容老状态）。
LOG = os.path.join(HERE, "tunnel.log")
LOG_ALT = os.path.join(HERE, "tunnel.err")
URLFILE = os.path.join(HERE, "tunnel_url.txt")
STATE = os.path.join(HERE, "tunnel_guard_state.json")
PROXY = os.path.join(HERE, "dsh_proxy.py")
PROXY_PORT = 3081
TOKEN = "xb7k2m9q"
TARGET = "http://127.0.0.1:3081"
PAT = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

CHECK_SECS = 60            # 每分钟查一次进程
PROBE_SECS = 300           # 每 5 分钟从公网探一次

# ★★★ 推送节流（用户明确要求：别浪费次数）
#
# 踩过的坑：第一次接上看门狗，一下就推了 3 条 ——
#   ① 手动推了一次网址
#   ② 看门狗首跑时状态文件不存在，被当成"网址更新"又推
#   ③ 我清掉状态重跑，又推
# ⇒ 微信推送（Server酱）有免费额度，这么刷很快就用完了。
#
# 现在的规矩：
#   ① **首次观察不推** —— 没有旧网址就只是"记下来"，那不是"变化"
#   ② 冷却时间：两次推送至少隔 PUSH_COOLDOWN 秒
#   ③ 每日上限：一天最多 PUSH_MAX_PER_DAY 条
#   ④ 只有【网址真的变了】（旧网址存在且不同）或者【隧道断过又恢复】才推
PUSH_COOLDOWN = 1800       # 30 分钟
PUSH_MAX_PER_DAY = 3


def sh(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace")
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


def port_listening(port):
    rc, out = sh("netstat -ano")
    for ln in out.split("\n"):
        if (":%d" % port) in ln and "LISTENING" in ln:
            return True
    return False


def procs(name):
    rc, out = sh('tasklist /FI "IMAGENAME eq %s" /NH' % name)
    return out.count(name)


def read_url():
    """从隧道日志里取【最新】的网址

    ★ 取最后一个（hits[-1]）而不是第一个：
      cloudflared 重启会把新网址【追加】到日志后面，
      取第一个会拿到已经失效的旧地址。
    ★ 主日志（tunnel.log）读不到时退回老文件（tunnel.err），
      免得升级过程中断档。
    """
    for p in (LOG, LOG_ALT):
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = PAT.findall(txt)
        if hits:
            return hits[-1]
    return None


def should_push(st, reason):
    """要不要推微信 —— 用户明确要求：最多一次，别浪费次数

    ★ 三个闸门，全过才推：
        ① 首见不推：没有旧网址就只是记录，不算"变化"
        ② 冷却：距上次推送 < PUSH_COOLDOWN 秒就不推
        ③ 每日上限：今天推够 PUSH_MAX_PER_DAY 条就不推
    """
    now = time.time()

    # ① 首次观察不推（★ 这条是这次刷屏的根因）
    if reason == "url_changed" and not st.get("prev_url"):
        print("  [推送] 首次见到网址，只记录不推送", flush=True)
        return False

    # ② 冷却
    gap = now - (st.get("last_push") or 0)
    if gap < PUSH_COOLDOWN:
        print("  [推送] 距上次推送才 %.0f 秒（冷却 %d 秒），跳过"
              % (gap, PUSH_COOLDOWN), flush=True)
        return False

    # ③ 每日上限
    today = time.strftime("%Y-%m-%d")
    if st.get("push_day") != today:
        st["push_day"] = today
        st["push_count"] = 0
    if int(st.get("push_count") or 0) >= PUSH_MAX_PER_DAY:
        print("  [推送] 今天已推 %s 条（上限 %d），跳过"
              % (st.get("push_count"), PUSH_MAX_PER_DAY), flush=True)
        return False

    return True


def mark_pushed(st):
    st["last_push"] = time.time()
    st["push_count"] = int(st.get("push_count") or 0) + 1


def push(title, body):
    """推微信（推不出去也不影响主流程）"""
    try:
        import notify_url
        key = notify_url.load_key()
        if not key:
            return False
        ok, _ = notify_url.push(key, title, body)
        return ok
    except Exception as e:
        print("  [推送失败] %s" % e, flush=True)
        return False


def start_proxy():
    print("  → 拉起代理 dsh_proxy.py", flush=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([sys.executable, PROXY],
                     cwd=HERE, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    return port_listening(PROXY_PORT)


def start_tunnel():
    print("  → 拉起隧道 cloudflared", flush=True)
    if not os.path.exists(CF):
        print("    ★ 找不到 %s" % CF, flush=True)
        return None
    # 清空日志，免得读到旧网址
    open(LOG, "w").close()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([CF, "tunnel", "--no-autoupdate", "--url", TARGET],
                     cwd=HERE, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=open(LOG, "w"))
    # 等网址出现
    url = None
    for _ in range(60):
        time.sleep(1)
        url = read_url()
        if url:
            break
    return url


def probe(url, timeout=25):
    """从公网真打一次（走 cloudflare 边缘绕回来）

    ★★★ 判据：2xx 和 3xx 都算通。
      踩过：原来只认 200/302，但带 ?k=口令 访问时，
      dsh_proxy 会先 303 重定向到首页（设完 cookie）——
      303 是**正常**的，却被判成"不通"，然后看门狗就会去重启隧道，
      越重启越乱。
      ⇒ 只要不是 4xx/5xx/000（连不上）就算活着。
    """
    rc, out = sh('curl -s -o NUL -w "%%{http_code}" --max-time %d "%s/?k=%s"'
                 % (timeout, url, TOKEN), timeout + 10)
    return out.strip()[-3:] if out.strip() else "?"


def probe_ok(code):
    """公网探测结果算不算"通"""
    if not code or len(code) != 3 or not code.isdigit():
        return False
    return code[0] in ("2", "3")      # 2xx / 3xx 都算


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def check_once(verbose=True, do_probe=True):
    """检查一轮；返回当前状态 dict"""
    st = load_state()
    changed = []

    # ---- ① 代理 ----
    if not port_listening(PROXY_PORT):
        changed.append("代理挂了")
        if verbose:
            print("[%s] ★ 代理不在 3081，拉起" % time.strftime("%H:%M:%S"),
                  flush=True)
        ok = start_proxy()
        changed.append("代理重启%s" % ("成功" if ok else "失败"))

    # ---- ② 隧道 ----
    if procs("cloudflared.exe") == 0:
        changed.append("隧道挂了")
        if verbose:
            print("[%s] ★ cloudflared 不在，拉起" % time.strftime("%H:%M:%S"),
                  flush=True)
        url = start_tunnel()
        if url:
            changed.append("新网址 %s" % url)
        else:
            changed.append("隧道重启失败")

    # ---- ③ 网址 ----
    url = read_url() or (open(URLFILE, encoding="utf-8").read().strip()
                         if os.path.exists(URLFILE) else None)
    if url:
        prev = st.get("url")
        if url != prev:
            with open(URLFILE, "w", encoding="utf-8") as f:
                f.write(url)
            st["prev_url"] = prev          # ★ 记住"上一个"，首见时是 None
            st["url"] = url
            changed.append("网址更新")
            if verbose:
                print("[%s] 网址: %s（上一个: %s）"
                      % (time.strftime("%H:%M:%S"), url, prev or "无"),
                      flush=True)
            # ★ 只有真的从"旧网址"变成"新网址"才推；首见不推
            if should_push(st, "url_changed"):
                if push("系统管家小白 · 手机入口",
                        "隧道网址变了，请用新的：\n\n**手机点这个：**\n\n"
                        "%s/?k=%s\n\n局域网：\nhttp://%s:%d/?k=%s"
                        % (url, TOKEN, lan_ip(), PROXY_PORT, TOKEN)):
                    mark_pushed(st)
                    if verbose:
                        print("  [推送] 已通知新网址", flush=True)
        else:
            st["url"] = url

    # ---- ④ 从公网探一次 ----
    if url and do_probe:
        now = time.time()
        if now - (st.get("last_probe") or 0) > PROBE_SECS:
            code = probe(url)
            st["last_probe"] = now
            st["last_code"] = code
            if verbose:
                print("[%s] 公网探测: HTTP %s" % (time.strftime("%H:%M:%S"), code),
                      flush=True)
            if not probe_ok(code):
                changed.append("公网探测 HTTP %s" % code)
                # 连续两次不通才重启，避免偶发抖动误杀
                st["bad_count"] = int(st.get("bad_count") or 0) + 1
                if st["bad_count"] >= 2:
                    if verbose:
                        print("  ★ 连续两次探测不通，重启隧道", flush=True)
                    sh('taskkill /F /IM cloudflared.exe', 15)
                    time.sleep(2)
                    url2 = start_tunnel()
                    st["bad_count"] = 0
                    if url2:
                        st["url"] = url2
                        changed.append("重建隧道 + 新网址")
                        # ★ 网址变了也要过节流（冷却 + 每日上限）
                        if should_push(st, "url_changed"):
                            if push("系统管家小白 · 手机入口（网址变了）",
                                    "隧道重建了，网址变了。\n\n**新网址：**\n\n"
                                    "%s/?k=%s" % (url2, TOKEN)):
                                mark_pushed(st)
            else:
                st["bad_count"] = 0

    st["last_check"] = time.time()
    st["changed"] = changed
    save_state(st)
    return st


def lan_ip():
    """取本机当前的局域网 IPv4

    ★ 2026-10-03 加：原来通知和 --status 里把局域网地址写死成
      192.168.110.21，换个网络（现在是 192.168.0.39）就变成错的了。
      ⇒ 动态取：连一下 8.8.8.8（不真发包，只为让内核选出出口网卡）。
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def status():
    st = load_state()
    # ★★★ 网址以【实时读日志】为准，state 只当兜底（2026-10-03）
    #   踩过：state 里存的是上次检查时的值；隧道重启换了网址之后，
    #         如果只看 state，--status 会一直显示已经失效的旧地址。
    url = read_url() or st.get("url")
    if not url and os.path.exists(URLFILE):
        try:
            url = open(URLFILE, encoding="utf-8").read().strip() or None
        except OSError:
            pass
    # 顺带把正确网址写回 state / 文件，免得别处再读到旧的
    if url and url != st.get("url"):
        st["prev_url"] = st.get("url")
        st["url"] = url
        save_state(st)
        try:
            with open(URLFILE, "w", encoding="utf-8") as f:
                f.write(url)
        except OSError:
            pass
    print("=" * 70)
    print(" 手机入口状态")
    print("=" * 70)
    print(" 代理 3081:      %s" % ("✓ 在" if port_listening(PROXY_PORT) else "✗ 不在"))
    print(" cloudflared:    %s" % ("✓ 在" if procs("cloudflared.exe") else "✗ 不在"))
    print(" 公网网址:       %s" % (url or "(还没有)"))
    print(" 最后一次探测:   HTTP %s  @ %s"
          % (st.get("last_code", "?"),
             time.strftime("%H:%M:%S", time.localtime(st.get("last_probe") or 0))
             if st.get("last_probe") else "从未"))
    if url:
        print()
        print(" 手机打开:")
        print("   %s/?k=%s" % (url, TOKEN))
        print(" 局域网:")
        print("   http://%s:%d/?k=%s" % (lan_ip(), PROXY_PORT, TOKEN))
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        status()
        return 0

    if a.once:
        st = check_once()
        print("状态:", json.dumps(st, ensure_ascii=False)[:300])
        return 0

    print("=" * 70)
    print(" 手机入口看门狗")
    print("=" * 70)
    print(" 每 %d 秒查进程，每 %d 秒从公网探一次" % (CHECK_SECS, PROBE_SECS))
    print(" 只在状态变化时推微信")
    print()

    while True:
        try:
            check_once()
        except KeyboardInterrupt:
            print("\n退出")
            return 0
        except Exception as e:
            print("[%s] 检查出错: %s: %s"
                  % (time.strftime("%H:%M:%S"), type(e).__name__, e), flush=True)
        time.sleep(CHECK_SECS)


if __name__ == "__main__":
    sys.exit(main() or 0)
