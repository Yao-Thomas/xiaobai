#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_svc_matrix_valid.py —— 给 audio_svc.spectral_matrix 加有效性判定

和 matrix_vol.py 是同一类问题：

  1. 全零轮次（故障 B：采集整段失败）没有识别，会被当成"没命中"，
     而且贡献 flatness = 0.0，把 min_flatness 拉到 0 —— 报告里看起来
     像"过载"，其实根本没采到数据。
  2. ★ **假命中**：e 全零时 max(e)=0，e.index(0)=0 -> top 恒等于 freqs[0]。
     如果那一轮播的正好是 freqs[0]，就会被错判成"对角线命中"。
  3. 没有有效性标志，调用方无从区分"采到了但过载"和"没采到"。
  4. 没有零采集统计。

改法：
  * 每行加 "valid": max(e) > 0
  * hit 只在 valid 行上统计
  * min_flatness 只在 valid 行上取
  * 返回值加 zero_captures / valid_rows
  * good 要求**全部 6 行都有效**
"""
import io
import sys

P = "ui/audio_svc.py"
src = io.open(P, encoding="utf-8").read()

if '"valid"' in src and "zero_captures" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

OLD = '''                    top = e.index(max(e))
                    med = sorted(e)[len(e) // 2] or 1e-9
                    rows.append({
                        "play": f0,
                        "energy": [round(x, 1) for x in e],
                        "top": freqs[top],
                        "hit": (top == freqs.index(f0)),'''

NEW = '''                    # ★ 有效性（故障 B）：全零 = 这一次没采到数据。
                    #   必须**先判 valid**：e 全零时 max(e)=0，e.index(0)=0，
                    #   top 会恒等于 freqs[0]，从而把"没采到"错判成"命中"。
                    valid = max(e) > 0
                    top = e.index(max(e)) if valid else -1
                    med = sorted(e)[len(e) // 2] or 1e-9
                    rows.append({
                        "play": f0,
                        "energy": [round(x, 1) for x in e],
                        "top": freqs[top] if valid else None,
                        "valid": valid,
                        "hit": bool(valid and top == freqs.index(f0)),'''

if OLD not in src:
    print("  [!] 锚点1 没找到")
    sys.exit(1)
src = src.replace(OLD, NEW, 1)
print("  OK: 每行加 valid，修掉假命中")

# ---- flatness 那行的 med 在 e 全零时是 1e-9，max 是 0 -> 0.0。
#      保留这个数（它现在只是参考），但 minflat 只在 valid 行上取。
OLD2 = '''                hit = sum(1 for r in rows if r["hit"])
                minflat = min((r["flatness"] for r in rows), default=0.0)
                good = bool(hit >= len(freqs) - 1 and minflat > 100)'''
NEW2 = '''                hit = sum(1 for r in rows if r["hit"])
                vrows = [r for r in rows if r.get("valid")]
                # ★ min_flatness 只在**有效**行上取。全零行的 flatness 是 0.0，
                #   混进来会把结果拉到 0，看起来像"过载"，其实没采到数据。
                minflat = min((r["flatness"] for r in vrows), default=0.0)
                zero_captures = len(rows) - len(vrows)
                # ★ good 要求六行全部有效
                good = bool(len(vrows) == len(freqs)
                            and hit >= len(freqs) - 1 and minflat > 100)'''
if OLD2 not in src:
    print("  [!] 锚点2 没找到")
    sys.exit(1)
src = src.replace(OLD2, NEW2, 1)
print("  OK: min_flatness 只在有效行上取 + good 要求全部有效")

# ---- 返回值补字段
OLD3 = '''                    "hit": hit, "total": len(freqs),
                    "min_flatness": minflat,'''
NEW3 = '''                    "hit": hit, "total": len(freqs),
                    "min_flatness": minflat,
                    "valid_rows": len(vrows),
                    "zero_captures": zero_captures,'''
if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)
    print("  OK: 返回值加 valid_rows / zero_captures")
else:
    print("  [!] 锚点3 没找到（返回值字段）")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("audio_svc.py syntax OK")
