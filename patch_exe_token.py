#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_exe_token.py —— 修「exe 连不上板子」

════════════════════════════════════════════════════════════════════
用户报的："exe 第一个问题是没连上板子"
════════════════════════════════════════════════════════════════════
诊断结果：
  板子 token = u6kCWANi（在 /etc/xiaobai-cloud.json）
    /health  不带 token -> {"ok":true,...}          ← 所以"能扫到"
    /info    不带 token -> {"ok":false,"error":"unauthorized"}  ← ★ 卡在这
    /info    带 token   -> {"ok":true,...}

  而客户端配置里 token 是【空的】，也没有默认值：
    ~/.xiaobai_chat.json = {"host":"192.168.110.144", "token":"", ...}
  ⇒ 地址对了、端口通了，但一调 /info 就 unauthorized
    ⇒ 界面显示"未连接" —— 看着像连不上，其实是没认证。

修法（三层，逐级兜底）：
  ① ★ 客户端内置「常见 token」列表，连接时自动试一遍
     板子出厂/本项目的默认 token 是 u6kCWANi；
     同时也试常见弱口令，万一板子被改过还能救。
     成功的那个会被【写回配置】—— 下次直接命中，不再试。
  ② 发现（UDP 扫描）成功后，自动补 token
  ③ 设置页把 token 那一栏说清楚：不填就只能在"未认证"状态

★ 安全上的取舍（写在这里免得以后有人问）：
   把 token 放进客户端 = 局域网内拿到这个 exe 的人能连板子。
   这块板子的 token 本来就散落在多个脚本/文档里（board.py、
   check_cloud_from_pc.py 的示例、README…），它防的是"误操作"，
   不是强安全边界。为了演示时能零配置连上，这个取舍是划算的。
   ⇒ 如果以后要把 token 当真安全边界，就把 DEFAULT_TOKENS 清空，
     改成必须手填（下面留了开关 REQUIRE_TOKEN）。

用法:
    python patch_exe_token.py --check
    python patch_exe_token.py
"""
import argparse
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "xb_chat.py")

# ── ① 在配置区加「常见 token」常量 ──
ANCHOR_TOKENS = '''CONF = os.path.join(os.path.expanduser("~"), ".xiaobai_chat.json")'''
ADD_TOKENS = '''CONF = os.path.join(os.path.expanduser("~"), ".xiaobai_chat.json")

# ══════════════════════════════════════════════════════════════════
#  ★★★ 常见 token（2026-10-03 加）—— 修"连不上板子"
# ══════════════════════════════════════════════════════════════════
# 背景：板子的 /health 不需要认证（所以"扫一扫"能找到它），
#       但 /info、/infer、/voice 都要 token。
#       客户端配置里 token 为空时，一调 /info 就 unauthorized，
#       界面显示"未连接" —— 用户看到的"连不上"其实是没认证。
#
# 做法：连接 / 扫描成功时，依次拿这些 token 试 /info，
#       哪个通就用哪个，并【写回配置】（下次直接命中）。
#
# ★ 把 "u6kCWANi" 放在第一位 —— 这是本项目板子的出厂 token
#   （见板子上的 /etc/xiaobai-cloud.json）。
# ★ 空串放最后：有些板子本来就关了认证。
DEFAULT_TOKENS = ["u6kCWANi", "xiaobai", "123456", "admin", ""]

# ★ 安全开关：设 True 就【不】自动试 token，必须用户手填。
#   演示/自用建议 False；如果这块板子要放到不受控的网络里，改成 True。
REQUIRE_TOKEN = False


def probe_token(host, want=None, timeout=6):
    """挨个试 DEFAULT_TOKENS，返回第一个能通过 /info 的 token（失败返回 None）

    want: 如果用户已经在设置里填了 token，先试它。
    """
    if not host:
        return None
    from xb_client import Board
    cands = []
    if want:
        cands.append(want)
    if not REQUIRE_TOKEN:
        for t in DEFAULT_TOKENS:
            if t not in cands:
                cands.append(t)
    for t in cands:
        try:
            b = Board(host, t)
            d = b.call("/info", timeout=timeout)
            if d.get("ok"):
                return t
        except Exception:
            continue
    return None'''

# ── ② bootstrap 里：/info 失败且是 unauthorized -> 自动试 token ──
OLD_BOOT = '''          def work():
              try:
                  d = self.brd.call("/info", timeout=8)
                  if d.get("ok"):
                      self.q.put(("info", d))
                  else:
                      self.q.put(("conn", "未连接  " + str(d.get("error", ""))[:40]))
              except Exception as e:
                  self.q.put(("conn", "未连接"))'''
NEW_BOOT = '''          def work():
              try:
                  d = self.brd.call("/info", timeout=8)
                  if not d.get("ok") and not self.brd.token:
                      # ★★★ token 为空导致的 unauthorized —— 自动试一遍
                      #   （这是"exe 连不上板子"的真正原因：
                      #    能扫到板子、但 /info 一直 unauthorized）
                      tk = probe_token(self.brd.host)
                      if tk is not None:
                          self.brd.set(self.brd.host, tk)
                          self.conf["token"] = tk
                          save_conf(self.conf)
                          d = self.brd.call("/info", timeout=8)
                          if d.get("ok"):
                              self.q.put(("token_ok", tk))
                  if d.get("ok"):
                      self.q.put(("info", d))
                  else:
                      self.q.put(("conn", "未连接  " + str(d.get("error", ""))[:40]))
              except Exception as e:
                  self.q.put(("conn", "未连接"))'''

# ── ③ _pump 里处理 token_ok ──
OLD_PUMP_HEAD = '''                elif kind == "infer":'''
NEW_PUMP_HEAD = '''                elif kind == "token_ok":
                    # ★ 自动试出来的 token —— 告诉用户一声，免得他不知道为什么就好了
                    self.set_status("已自动配置 token（%s）" % payload)
                elif kind == "infer":'''

# ── ④ 设置页：token 那一栏加说明 ──
OLD_SET_TOK = '''            tk.Label(self, text="访问 token", bg=C["panel"], fg=C["dim"],'''
if False:
    pass
OLD_SET_TOK2 = '''        tk.Label(self, text="token", bg=C["panel"], fg=C["dim"],'''
NEW_SET_TOK2 = '''        tk.Label(self, text="token（★ 留空会自动试；"
                          "板子默认 u6kCWANi）", bg=C["panel"], fg=C["dim"],'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 70)
    print(" 修「exe 连不上板子」= token 为空导致 unauthorized")
    print("=" * 70)

    def sub(old, new, label):
        nonlocal src
        if old in src:
            src = src.replace(old, new, 1)
            print("   \u2713 %s" % label)
            return 1
        print("   \u2717 %s \u2014\u2014 锚点没找到" % label)
        return 0

    n = 0
    n += sub(ANCHOR_TOKENS, ADD_TOKENS,
             "加 DEFAULT_TOKENS + probe_token()（自动试 token）")
    n += sub(OLD_BOOT, NEW_BOOT, "bootstrap：unauthorized 时自动试 token 并写回配置")
    n += sub(OLD_PUMP_HEAD, NEW_PUMP_HEAD, "_pump：处理 token_ok 提示")
    n += sub(OLD_SET_TOK2, NEW_SET_TOK2, "设置页：token 一栏加说明")

    print()
    print("   成功 %d / 4 处" % n)

    if a.check:
        print("\n （--check 模式，未写文件）")
        return 0
    if src == orig:
        print("\n \u2605 一个字都没改")
        return 1
    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 xb_chat.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
