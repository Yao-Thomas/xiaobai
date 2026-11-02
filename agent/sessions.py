#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sessions.py —— 对话管理：会话持久化 + 上下文裁剪 + 多会话

════════════════════════════════════════════════════════════════════
要解决的问题
════════════════════════════════════════════════════════════════════
云协同的 `/chat` 端点原来是"会话存内存字典"：
    · 服务重启 -> 全部会话丢光
    · 客户端换了（手机 → PC）-> 看不到刚才聊的
    · 没有列表、没有删除、没有导出
    · 上下文无限涨 -> 迟早把 1GB 内存吃光

════════════════════════════════════════════════════════════════════
做了四件事
════════════════════════════════════════════════════════════════════,
    ① 持久化      每个会话一个 JSON 文件，放 /var/lib/xiaobai/sessions/
    ② 上下文裁剪  超过上限就丢【最老的工具结果】（保留对话骨架）
    ③ 多会话      列表 / 新建 / 删除 / 重命名 / 导出
    ④ 容量控制    最多 N 个会话、单会话最多 M 条消息，超了就淘汰最老的

★ 为什么"丢工具结果"而不是"丢整轮"：
  对话的骨架（用户问了什么、助手说了什么）是理解上下文的关键；
  工具返回的那一大坨（比如 dmesg 几百行）才是占地方的。
  Harness 里也是这个思路（见 core.py 的压缩逻辑）。

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    from agent.sessions import Store
    st = Store()
    sid = st.new("现在多少度")              # 新建会话
    st.append(sid, "user", "现在多少度")
    st.append(sid, "assistant", "69.8 度")
    st.history(sid)                         # 拿上下文（已裁剪）
    st.list()                               # 会话列表
    st.delete(sid)
    st.export(sid)                          # 导出成 markdown

    python3 sessions.py --selftest
    python3 sessions.py --list
    python3 sessions.py --show <id>
"""
import datetime
import json
import os
import re
import shutil
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STORE_DIR = os.environ.get("XIAOBAI_SESSION_DIR", "/var/lib/xiaobai/sessions")

# ---- 容量上限（板子只有 1GB 内存 + 有限 flash，得克制）----
MAX_SESSIONS = 40            # 最多留多少个会话
MAX_MSGS = 60                # 单会话最多多少条消息
MAX_TOOL_CHARS = 4000        # 单条工具结果最多留多少字符
MAX_TOTAL_CHARS = 60000      # 单会话全部内容的上限（超了就裁工具结果）


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_id(s):
    return re.sub(r"[^A-Za-z0-9_\-]", "", str(s or ""))[:64]


class Store(object):
    def __init__(self, root=None, verbose=False):
        self.root = root or STORE_DIR
        self.verbose = verbose
        self.lock = threading.RLock()
        try:
            os.makedirs(self.root, exist_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------ 路径
    def _path(self, sid):
        return os.path.join(self.root, _safe_id(sid) + ".json")

    def _meta_path(self, sid):
        return os.path.join(self.root, _safe_id(sid) + ".meta")

    # ------------------------------------------------------------ 读
    def load(self, sid):
        p = self._path(sid)
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            if self.verbose:
                print("[sessions] 读 %s 失败: %s" % (sid, e))
            return None

    def _save(self, sess):
        sid = sess.get("id")
        if not sid:
            return False
        p = self._path(sid)
        tmp = p + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sess, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)          # ★ 原子替换，别写坏
            return True
        except Exception as e:
            if self.verbose:
                print("[sessions] 写 %s 失败: %s" % (sid, e))
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    # ------------------------------------------------------------ 新建
    def new(self, first_text="", sid=None):
        """新建一个会话，返回 id"""
        with self.lock:
            if not sid:
                sid = "s_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") \
                      + "_%03d" % (int(time.time() * 997) % 1000)
            sid = _safe_id(sid) or ("s_%d" % int(time.time()))
            sess = {
                "id": sid,
                "created": _now(),
                "updated": _now(),
                # ★ 排序用的高精度时间戳。
                #   为什么不用 updated：它只精确到【秒】，
                #   同一秒内建的多个会话时间戳一样，排序结果就不确定了
                #   （离线测试抓出来的："最新的排最前"偶发失败）。
                "seq": time.time(),
                "turns": 0,
                "title": (first_text or "")[:40],
                "messages": [],
            }
            self._save(sess)
            self._evict()
            return sid

    # ------------------------------------------------------------ 追加
    def append(self, sid, role, content, tool_calls=None, name=None):
        """追加一条消息。会话不存在就自动建（客户端只要给个 id 就行）"""
        with self.lock:
            sess = self.load(sid)
            if sess is None:
                sess = {"id": _safe_id(sid), "created": _now(),
                        "updated": _now(), "seq": time.time(), "turns": 0,
                        "title": (content or "")[:40], "messages": []}
            msg = {"role": role, "content": content or "",
                   "ts": _now()}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if name:
                msg["name"] = name
            sess["messages"].append(msg)
            if role == "user" and not sess.get("title"):
                sess["title"] = (content or "")[:40]
            if role == "assistant":
                sess["turns"] = int(sess.get("turns") or 0) + 1
            sess["updated"] = _now()
            sess["seq"] = time.time()      # ★ 排序用（高精度）
            self._trim(sess)
            self._save(sess)
            return True

    # ------------------------------------------------------------ 裁剪
    def _trim(self, sess):
        """上下文裁剪

        两级：
          ① 消息条数超了 -> 从最老的开始丢（但保留最早那条 user，作为话题锚点）
          ② 总字符数超了 -> 只把【工具结果】压短（不动对话骨架）
        """
        msgs = sess.get("messages") or []

        # ① 条数
        if len(msgs) > MAX_MSGS:
            keep_first = msgs[:1] if msgs and msgs[0].get("role") == "user" \
                else []
            tail = msgs[-(MAX_MSGS - len(keep_first)):]
            msgs = keep_first + tail
            sess["messages"] = msgs

        # ② 单条工具结果太长 -> 截断
        for m in msgs:
            c = m.get("content") or ""
            if len(c) > MAX_TOOL_CHARS:
                m["content"] = c[:MAX_TOOL_CHARS] + \
                    "\n…（已省略 %d 字）" % (len(c) - MAX_TOOL_CHARS)

        # ③ 总量还超 -> 把最老的工具结果换成占位符
        def total():
            return sum(len(m.get("content") or "") for m in msgs)

        i = 0
        while total() > MAX_TOTAL_CHARS and i < len(msgs):
            m = msgs[i]
            c = m.get("content") or ""
            if m.get("role") in ("tool",) or c.startswith("{") or \
                    c.startswith("[") or len(c) > 500:
                if not c.startswith("…"):
                    m["content"] = "…（较早的工具结果已省略 %d 字）" % len(c)
            i += 1
        return sess

    # ------------------------------------------------------------ 上下文
    def history(self, sid, limit=None):
        """拿给模型用的上下文（已裁剪）"""
        sess = self.load(sid)
        if not sess:
            return []
        msgs = sess.get("messages") or []
        out = []
        for m in msgs:
            d = {"role": m.get("role"), "content": m.get("content") or ""}
            if m.get("tool_calls"):
                d["tool_calls"] = m["tool_calls"]
            if m.get("name"):
                d["name"] = m["name"]
            out.append(d)
        if limit:
            out = out[-limit:]
        return out

    def turns(self, sid):
        sess = self.load(sid)
        return int((sess or {}).get("turns") or 0)

    # ------------------------------------------------------------ 列表
    def list(self, limit=MAX_SESSIONS):
        """会话列表（新的在前）"""
        out = []
        try:
            files = [f for f in os.listdir(self.root) if f.endswith(".json")]
        except Exception:
            return out
        for f in files:
            try:
                with open(os.path.join(self.root, f), encoding="utf-8") as fh:
                    s = json.load(fh)
            except Exception:
                continue
            msgs = s.get("messages") or []
            last_user = ""
            for m in reversed(msgs):
                if m.get("role") == "user":
                    last_user = (m.get("content") or "")[:40]
                    break
            out.append({
                "id": s.get("id"),
                "created": s.get("created"),
                "updated": s.get("updated"),
                "seq": s.get("seq") or 0,
                "turns": s.get("turns", 0),
                "messages": len(msgs),
                "title": s.get("title") or last_user or "(空)",
                "preview": last_user,
            })
        # ★ 按 seq（高精度）排，没有 seq 的老记录退回用 updated 字符串
        out.sort(key=lambda x: (x.get("seq") or 0,
                                x.get("updated") or ""), reverse=True)
        return out[:limit]

    # ------------------------------------------------------------ 删 / 改
    def delete(self, sid):
        p = self._path(sid)
        if not os.path.exists(p):
            return False
        try:
            os.remove(p)
            return True
        except Exception:
            return False

    def clear_all(self):
        n = 0
        for s in self.list(limit=10000):
            if self.delete(s["id"]):
                n += 1
        return n

    def rename(self, sid, title):
        with self.lock:
            sess = self.load(sid)
            if not sess:
                return False
            sess["title"] = (title or "")[:60]
            sess["updated"] = _now()
            return self._save(sess)

    def _evict(self):
        """会话太多了就淘汰最老的（按 updated）"""
        ss = self.list(limit=10000)
        if len(ss) <= MAX_SESSIONS:
            return 0
        n = 0
        for s in ss[MAX_SESSIONS:]:
            if self.delete(s["id"]):
                n += 1
        return n

    # ------------------------------------------------------------ 导出
    def export(self, sid, fmt="md"):
        """导出成 markdown（给用户留档 / 交给评审看）"""
        sess = self.load(sid)
        if not sess:
            return None
        if fmt != "md":
            return json.dumps(sess, ensure_ascii=False, indent=1)
        lines = ["# 对话记录 %s" % sess.get("id"),
                 "",
                 "- 开始：%s" % sess.get("created"),
                 "- 最后：%s" % sess.get("updated"),
                 "- 轮数：%s" % sess.get("turns"),
                 "- 标题：%s" % sess.get("title"),
                 "",
                 "---",
                 ""]
        for m in sess.get("messages") or []:
            role = m.get("role")
            who = {"user": "🧑 用户", "assistant": "🤖 小白",
                   "tool": "🔧 工具", "system": "⚙️ 系统"}.get(role, role)
            lines.append("## %s  ·  %s" % (who, m.get("ts")))
            lines.append("")
            lines.append("```")
            lines.append((m.get("content") or "")[:4000])
            lines.append("```")
            lines.append("")
        return "\n".join(lines)

    def stats(self):
        ss = self.list(limit=10000)
        total_b = 0
        try:
            for f in os.listdir(self.root):
                total_b += os.path.getsize(os.path.join(self.root, f))
        except Exception:
            pass
        return {
            "sessions": len(ss),
            "max_sessions": MAX_SESSIONS,
            "max_msgs": MAX_MSGS,
            "bytes": total_b,
            "dir": self.root,
        }


# ══════════════════════════════════════════════════════════════════
#  自测
# ══════════════════════════════════════════════════════════════════
def selftest():
    import tempfile
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        if not c:
            ok = False

    print("=" * 78)
    print(" 对话管理自测")
    print("=" * 78)

    tmp = tempfile.mkdtemp(prefix="sess_")
    st = Store(root=tmp)

    print("\n【1】新建 / 追加 / 读回")
    sid = st.new("你好")
    chk(bool(sid) and sid.startswith("s_"), "新建返回 id", sid)
    st.append(sid, "user", "现在多少度")
    st.append(sid, "assistant", "69.8 度")
    h = st.history(sid)
    chk(len(h) == 2, "读回 2 条", "%d 条" % len(h))
    chk(h[0]["role"] == "user" and h[1]["role"] == "assistant", "角色对")
    chk(st.turns(sid) == 1, "轮数=1", str(st.turns(sid)))

    print("\n【2】★ 持久化（重新打开 Store 还能读到）")
    st2 = Store(root=tmp)
    h2 = st2.history(sid)
    chk(len(h2) == 2, "★ 新 Store 实例读得到（真的落盘了）", "%d 条" % len(h2))
    chk(os.path.exists(os.path.join(tmp, sid + ".json")), "会话文件存在")

    print("\n【3】给不存在的 id 追加会自动建")
    st.append("s_new_auto", "user", "喂")
    chk(len(st.history("s_new_auto")) == 1, "自动建会话")

    print("\n【4】列表（新的在前）")
    time.sleep(0.05)
    sid3 = st.new("第二个")
    st.append(sid3, "user", "第二个会话")
    ls = st.list()
    chk(len(ls) >= 2, "列表有 %d 个" % len(ls))
    chk(ls[0]["id"] == sid3, "★ 最新的排最前", ls[0]["id"])
    chk("title" in ls[0] and "updated" in ls[0], "列表项有 title/updated")

    print("\n【5】★ 上下文裁剪：条数超上限")
    sid4 = st.new("长对话")
    for i in range(MAX_MSGS + 30):
        st.append(sid4, "user" if i % 2 == 0 else "assistant", "第 %d 条" % i)
    sess = st.load(sid4)
    n = len(sess["messages"])
    chk(n <= MAX_MSGS, "★ 条数被裁到 <= %d" % MAX_MSGS, "实际 %d" % n)
    chk(sess["messages"][0]["role"] == "user", "保留了最早那条 user（话题锚点）")

    print("\n【6】★ 上下文裁剪：单条工具结果太长要截断")
    sid5 = st.new("大输出")
    st.append(sid5, "tool", "X" * (MAX_TOOL_CHARS + 5000), name="dmesg")
    sess = st.load(sid5)
    c = sess["messages"][0]["content"]
    chk(len(c) <= MAX_TOOL_CHARS + 60, "★ 工具结果被截断",
        "%d 字符" % len(c))
    chk("已省略" in c, "截断处有说明")

    print("\n【7】★ 总量超上限：丢最老的工具结果，保留骨架")
    sid6 = st.new("很多大输出")
    st.append(sid6, "user", "帮我看看日志")
    for i in range(30):
        st.append(sid6, "tool", "Y" * 3000, name="log%d" % i)
    sess = st.load(sid6)
    total = sum(len(m.get("content") or "") for m in sess["messages"])
    chk(total <= MAX_TOTAL_CHARS + 2000, "★ 总量被压到上限内",
        "%d 字符" % total)
    chk(sess["messages"][0]["content"] == "帮我看看日志",
        "★ 最早的【用户提问】没有被改（骨架保住了）")

    print("\n【8】删除")
    chk(st.delete(sid3), "删除返回 True")
    chk(st.load(sid3) is None, "删了就没了")

    print("\n【9】重命名")
    chk(st.rename(sid, "温度问题"), "重命名成功")
    chk(st.load(sid)["title"] == "温度问题", "标题改了")

    print("\n【10】导出 markdown")
    md = st.export(sid, "md")
    chk(md and md.startswith("# 对话记录"), "导出成 md")
    chk("🧑 用户" in md and "🤖 小白" in md, "有角色标记")
    js = st.export(sid, "json")
    chk(js and js.startswith("{"), "也能导出 json")

    print("\n【11】★ 会话数上限：超了淘汰最老的")
    st7 = Store(root=tempfile.mkdtemp(prefix="sess2_"))
    for i in range(MAX_SESSIONS + 10):
        s = st7.new("第 %d 个" % i)
        st7.append(s, "user", "内容 %d" % i)
        time.sleep(0.002)
    n = len(st7.list(limit=10000))
    chk(n <= MAX_SESSIONS, "★ 会话数被控制在 %d 以内" % MAX_SESSIONS,
        "实际 %d" % n)

    print("\n【12】清空 + 统计")
    st9 = Store(root=tempfile.mkdtemp(prefix="sess3_"))
    for i in range(3):
        s = st9.new("x%d" % i)
        st9.append(s, "user", "y")
    chk(st9.clear_all() == 3, "清空 3 个")
    chk(len(st9.list()) == 0, "清空后列表为空")
    stats = st9.stats()
    chk("sessions" in stats and "bytes" in stats, "stats 有字段")

    print("\n【13】脏 id 不会逃出目录（安全）")
    st10 = Store(root=tempfile.mkdtemp(prefix="sess4_"))
    bad = st10.new("x", sid="../../etc/passwd")
    chk("/" not in bad and ".." not in bad, "★ 路径穿越的 id 被清洗",
        bad)
    p = os.path.join(st10.root, bad + ".json")
    chk(os.path.exists(p), "文件落在会话目录里")

    print("\n【14】坏文件不崩")
    st11 = Store(root=tempfile.mkdtemp(prefix="sess5_"))
    with open(os.path.join(st11.root, "broken.json"), "w") as f:
        f.write("{这不是 json")
    chk(isinstance(st11.list(), list), "列表跳过坏文件不崩")
    chk(st11.history("broken") == [], "读坏文件返回空")

    print()
    print("=" * 78)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 78)
    for d in (tmp,):
        shutil.rmtree(d, ignore_errors=True)
    return ok


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", default="")
    ap.add_argument("--export", default="")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--delete", default="")
    a = ap.parse_args()

    if a.selftest:
        return 0 if selftest() else 1

    st = Store(verbose=True)

    if a.stats:
        print(json.dumps(st.stats(), ensure_ascii=False, indent=1))
        return 0

    if a.list:
        ss = st.list()
        if not ss:
            print("没有会话")
        for s in ss:
            print("  %-26s %-16s %2d 轮  %s"
                  % (s["id"], s["updated"], s["turns"], s["title"][:30]))
        return 0

    if a.show:
        h = st.history(a.show)
        for m in h:
            print("[%s] %s" % (m["role"], (m.get("content") or "")[:200]))
        return 0

    if a.export:
        out = st.export(a.export, "md")
        if out is None:
            print("没有这个会话")
            return 1
        print(out)
        return 0

    if a.delete:
        print("删除", a.delete, "->", st.delete(a.delete))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
