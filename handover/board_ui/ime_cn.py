#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ime_cn.py —— 板载**本地**中文拼音输入法引擎（不联网）

════════════════════════════════════════════════════════════════════
为什么需要它
════════════════════════════════════════════════════════════════════
板载 Agent 是个**中文**语音助手，但原来的板载键盘（fbui.MiniKeyboard）
只有 `0-9 a-z . _ - /` —— **一个汉字都打不了**。
语音识别不准的时候，用户没法手动补输入。

════════════════════════════════════════════════════════════════════
方案：本地拼音输入
════════════════════════════════════════════════════════════════════
数据表 `ime_cn.json` 由 PC 上的 `build_ime_data.py` 生成：
  * 汉字 -> 拼音：pypinyin（主读音优先、次读音排后，避免罕见读音污染候选）
  * 候选排序：jieba 的 349,046 条词频表
  * 规模：418 个单字读音键 + 47,282 个词读音键，约 1.2 MB

查候选的顺序：
  1. 精确**词**匹配   "xianzai" -> 现在
  2. 精确**字**匹配   "hao"     -> 好 号 豪 ...
  3. **前缀**匹配     "xianz"   -> 现在（用二分查找，O(log n)，不是线性扫）

用法:
    from ime_cn import IME
    ime = IME()
    ime.candidates("xianzai")   # -> [('现在','word'), ('线在','word'), ...]
"""
import bisect
import json
import os

try:
    from pypinyin import Style, pinyin     # 板子上没有，正常
except Exception:
    pinyin = None

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "ime_cn.json")


class IME(object):
    def __init__(self, path=DEFAULT_PATH, per_key=10):
        self.path = path
        self.per_key = per_key
        self.words = {}
        self.chars = {}
        self._keys = []
        self._kfreq = []
        self.ok = False
        self.err = ""
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self.words = d.get("words", {})
            self.chars = d.get("chars", {})
            # ★ 优先用数据表里带的"已排序键 + 平行词频数组"。
            #   前缀匹配必须按**词频**排序；按字母序会出现
            #   "xianz" -> 闲杂 排在 现在 前面 这种怪结果。
            sk = d.get("word_keys_sorted")
            kf = d.get("word_kfreq")
            if sk and kf and len(sk) == len(kf):
                self._keys = sk
                self._kfreq = kf
            else:
                self._keys = sorted(self.words)
                self._kfreq = [1] * len(self._keys)
            self.ok = True
        except Exception as e:
            self.err = "%s: %s" % (type(e).__name__, e)

    # ---------------------------------------------------------- 前缀
    def _prefix_words(self, buf, limit):
        """返回以 buf 开头（且不等于 buf）的词，**按首候选词频降序**"""
        if not self._keys:
            return []
        lo = bisect.bisect_left(self._keys, buf)
        hi = bisect.bisect_left(self._keys, buf + "\uffff")
        if hi <= lo:
            return []
        cands = []
        for i in range(lo, min(hi, lo + 4000)):
            k = self._keys[i]
            if k == buf:
                continue
            vs = self.words.get(k)
            if vs:
                cands.append((self._kfreq[i] if i < len(self._kfreq) else 1,
                              vs[0]))
        cands.sort(key=lambda x: -x[0])
        out, seen = [], set()
        for _, w in cands:
            if w not in seen:
                seen.add(w)
                out.append(w)
                if len(out) >= limit:
                    break
        return out

    # ---------------------------------------------------------- 主接口
    def candidates(self, buf, limit=9):
        """给当前拼音缓冲，返回候选列表 [(文本, 'word'|'char')]

        顺序：精确词 > 精确字 > 前缀词
        去重，最多 limit 个。
        """
        buf = (buf or "").strip().lower()
        if not buf or not self.ok:
            return []
        out = []
        seen = set()

        def add(t, kind):
            if t and t not in seen:
                seen.add(t)
                out.append((t, kind))

        # 1) 精确词
        for w in self.words.get(buf, [])[:limit]:
            add(w, "word")
        # 2) 精确字
        if len(out) < limit:
            for c in self.chars.get(buf, [])[:limit]:
                add(c, "char")
        # 3) 前缀词（帮助用户少敲几个字母）
        if len(out) < limit:
            for w in self._prefix_words(buf, limit - len(out)):
                add(w, "word")
        return out[:limit]

    def has(self, buf):
        return bool(self.candidates(buf, limit=1))

    def stats(self):
        return {
            "ok": self.ok, "err": self.err,
            "chars_keys": len(self.chars), "word_keys": len(self.words),
            "path": self.path,
        }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ime = IME(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
    print("数据表:", ime.stats())
    for probe in ("xianzai", "hao", "yinyue", "bofang", "xianz", "ni",
                  "shijian", "tianqi", "ji", "z", "zzz"):
        cs = ime.candidates(probe)
        print("  %-9s -> %s" % (probe, " | ".join("%s(%s)" % (t, k)
                                                  for t, k in cs)))
