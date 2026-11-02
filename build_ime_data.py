#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_ime_data.py —— 生成板载中文输入法的数据表（拼音 -> 汉字/词）

════════════════════════════════════════════════════════════════════
为什么要在 PC 上生成
════════════════════════════════════════════════════════════════════
板子上要一个**本地**输入法（不联网）。但板子上：
  * espeak-ng 的 zh_dict 是**编译过的二进制**，提取麻烦
  * vosk 模型的词在 Gr.fst 里，也是二进制
  * 没有 pypinyin 之类的库

所以改在 PC 上生成一张紧凑表，发到板上用：
  * 汉字 -> 拼音：用 pypinyin（多音字取全部读音，这点很重要）
  * 候选排序：用 jieba 的 dict.txt（349,046 条词频，格式 "词 频次 词性"）

════════════════════════════════════════════════════════════════════
设计
════════════════════════════════════════════════════════════════════
输出 ime_cn.json:
  {
    "v": 1,
    "chars": { "<拼音>": ["先","现","线",...] },   # 单字，按词频降序
    "words": { "<拼音>": ["现在","线在",...] },    # 词，按词频降序
  }

输入法逻辑（板上）：
  * 用户敲 "xianzai" -> 先查 words["xianzai"] -> 显示候选
  * 没有精确匹配 -> 用前缀匹配 chars/words 里以 "xianzai" 开头的键
  * 完全没匹配 -> 只给字母

用法:
    python build_ime_data.py                    # 默认参数
    python build_ime_data.py --max-words 80000  # 调词表大小
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import jieba                                                  # noqa: E402
from pypinyin import Style, pinyin                            # noqa: E402

CJK = re.compile(r"^[\u4e00-\u9fff]+$")


def load_jieba_dict():
    """返回 [(词, 频次)]，只保留纯中文，按频次降序"""
    p = os.path.join(os.path.dirname(jieba.__file__), "dict.txt")
    items = []
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            w = parts[0]
            if not CJK.match(w):
                continue
            try:
                fr = int(parts[1])
            except ValueError:
                continue
            items.append((w, fr))
    items.sort(key=lambda x: -x[1])
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-chars", type=int, default=22000,
                    help="最多收多少单字")
    ap.add_argument("--max-words", type=int, default=80000,
                    help="最多收多少词")
    ap.add_argument("--per-key", type=int, default=12,
                    help="每个拼音最多留几个候选")
    ap.add_argument("--out", default="ime_cn.json")
    a = ap.parse_args()

    t0 = time.time()
    print("1) 读 jieba 词频表 ...")
    items = load_jieba_dict()
    print("   纯中文词条: %d" % len(items))

    chars_freq = [(w, f) for w, f in items if len(w) == 1]
    words_freq = [(w, f) for w, f in items if 2 <= len(w) <= 8]
    print("   单字 %d 个, 词 %d 个" % (len(chars_freq), len(words_freq)))

    chars_freq = chars_freq[:a.max_chars]
    words_freq = words_freq[:a.max_words]

    print("2) 单字 -> 拼音（主读音优先，次读音排后面）...")
    # ★ 两遍走：
    #   第一遍只收**主读音**（heteronym=False），按词频顺序，优先级最高；
    #   第二遍收**其余读音**，追加在后面。
    #   否则像"听"(tīng 常用 / yǐn 罕见) 会在 yin 下排在前面，污染候选。
    chars = collections.defaultdict(list)
    seen = set()
    done = 0
    for w, f in chars_freq:                      # 第一遍：主读音
        try:
            py = pinyin(w, style=Style.NORMAL)
        except Exception:
            continue
        if not py or not py[0]:
            continue
        reading = py[0][0]
        if reading and reading.isalpha():
            chars[reading].append(w)
            seen.add((reading, w))
        done += 1
        if done % 4000 == 0:
            print("      [主] ... %d" % done)

    print("      主读音键 %d，开始补次读音 ..." % len(chars))
    done = 0
    for w, f in chars_freq:                      # 第二遍：其余读音
        try:
            py = pinyin(w, style=Style.NORMAL, heteronym=True)
        except Exception:
            continue
        if not py or not py[0]:
            continue
        for reading in set(py[0]):
            if reading and reading.isalpha() and (reading, w) not in seen:
                chars[reading].append(w)
                seen.add((reading, w))
        done += 1
        if done % 4000 == 0:
            print("      [次] ... %d" % done)
    print("   单字读音键: %d" % len(chars))

    print("3) 词 -> 拼音 ...")
    words = collections.defaultdict(list)
    done = 0
    for w, f in words_freq:
        try:
            py = pinyin(w, style=Style.NORMAL)
        except Exception:
            continue
        key = "".join(x[0] for x in py if x and x[0])
        if key and key.isalpha():
            words[key].append(w)
        done += 1
        if done % 10000 == 0:
            print("      ... %d" % done)
    print("   词读音键: %d" % len(words))

    # 每个键按词频降序（原表已按频次降序，append 顺序即优先级），截断
    def trim(d):
        return {k: v[:a.per_key] for k, v in d.items() if v}

    data = {"v": 1, "chars": trim(chars), "words": trim(words)}

    # ★ 前缀匹配要按词频排序，不能按字母序。
    #   所以额外输出一个**与 sorted(words.keys()) 平行的词频数组**，
    #   第 i 个数 = 排好序后第 i 个键的"首候选词频"。
    #   （只存数字，比存 "键->频次" 的字典省很多）
    freq_of = {w: f for w, f in words_freq}
    skeys = sorted(data["words"])
    kfreq = []
    for k in skeys:
        top = data["words"][k][0]
        kfreq.append(int(freq_of.get(top, 1)))
    data["word_keys_sorted"] = skeys
    data["word_kfreq"] = kfreq

    with io.open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    sz = os.path.getsize(a.out)
    print("\n完成: %s   %.1f KB   用时 %.0f 秒"
          % (a.out, sz / 1024.0, time.time() - t0))
    print("  单字键 %d  词键 %d" % (len(data["chars"]), len(data["words"])))

    # 抽查几个常用输入
    print("\n抽查:")
    for probe in ("xianzai", "ji", "yinyue", "yin", "tianqi", "bofang",
                  "ni", "hao", "shijian"):
        c = data["chars"].get(probe, [])[:6]
        w = data["words"].get(probe, [])[:4]
        print("  %-9s 词:%-22s 字:%s"
              % (probe, " ".join(w) if w else "-", " ".join(c) if c else "-"))


if __name__ == "__main__":
    main()
