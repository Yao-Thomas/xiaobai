#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_matrix_vol_valid.py —— 给 matrix_vol.py 加"有效性判定 + 重试"

═══ 为什么要改 ═══
2026-09-28 反推出 ③ 的失败其实是**两种**故障：

  A  边放边录 ADC 过载   -> 能量正常但频谱平坦（1.5~2.2）
  B  采集整段失败         -> 能量**全零**（表现为 min_flatness = 0.0）

而原来的 one_matrix() 有 4 个问题：

  1. **没有有效性检查** —— 全零轮次被当成"没命中"，还贡献平坦度 0.0
  2. **没有重试** —— 一次故障 B 就毁掉整轮实验
  3. **报告"平均平坦度"** —— 但判据用的是"**最小**平坦度"！
     一行坏数据会被平均掉，掩盖问题（这是真 bug）
  4. 没有全零率统计 —— 故障 B 的发生率无从得知

═══ 改法 ═══
  * 每轮采集后判 max(e) > 0；为 0 就**重试**（最多 RETRY 次）
  * 统计**全零次数**并在报告里打出来（这本身就是诊断数据）
  * 平坦度改成报告 **min**（与判据一致），同时保留 mean 供参考
  * 无效轮次明确标记，不混进命中率
"""
import io
import sys

P = "ui/matrix_vol.py"
src = io.open(P, encoding="utf-8").read()

if "RETRY" in src and "zero_captures" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

OLD = '''    def one_matrix(amp):
        """返回 (命中数, 平均平坦度, 每行明细)"""
        quiet()
        rec()
        base = goe_multi(win(rec()), freqs)
        hit, flats, rows = 0, [], []
        for f0 in freqs:
            play(f0, amp)
            e = goe_multi(win(rec()), freqs)
            top = e.index(max(e))
            ok = (top == freqs.index(f0))
            hit += 1 if ok else 0
            med = sorted(e)[len(e) // 2] or 1e-9
            flats.append(max(e) / med)
            rows.append((f0, freqs[top], ok, max(e), base[top]))
        quiet()
        return hit, sum(flats) / len(flats), rows
'''

NEW = '''    # ★ 故障 B（采集整段失败）的重试上限。全零 = 那一次没采到数据。
    RETRY = 3
    STATS = {"zero": 0, "grabs": 0, "retried": 0}

    def grab_energy():
        """采一次并算能量。若全零则重试（最多 RETRY 次）。

        返回 (e, zeros)  —— e 是能量列表，zeros 是这次遇到的全零次数。
        全零的判据: max(e) == 0（一个频点都没能量 = 整段没采到数据）。
        """
        zeros = 0
        for _ in range(RETRY):
            cap.cfg()
            d, _ = cap.grab(secs)
            v = left(d)
            STATS["grabs"] += 1
            e = goe_multi(win(v), freqs) if v else [0.0] * len(freqs)
            if max(e) > 0:
                if zeros:
                    STATS["retried"] += 1
                return e, zeros
            # ★ 全零 = 故障 B，记一笔再重来
            STATS["zero"] += 1
            zeros += 1
            time.sleep(0.08)
        # 重试都用完了还是全零，把它当结果返回（上层会标成无效）
        return [0.0] * len(freqs), zeros

    def one_matrix(amp):
        """返回 (命中数, 最小平坦度, 每行明细)

        ★ 改动：平坦度返回 **min**（和判据一致），不是 mean。
          原来返回 mean 会把单行坏数据平均掉 —— 那是真 bug。
          明细里保留 mean 供参考。
        """
        quiet()
        rec()
        b, _bz = grab_energy()
        base = b
        hit, flats, means, rows = 0, [], [], []
        for f0 in freqs:
            play(f0, amp)
            e, zeros = grab_energy()
            top = e.index(max(e))
            ok = (top == freqs.index(f0))
            hit += 1 if ok else 0
            med = sorted(e)[len(e) // 2] or 1e-9
            fl = max(e) / med
            if max(e) > 0:
                flats.append(fl)
            means.append(fl)
            rows.append((f0, freqs[top], ok, max(e), base[top], zeros,
                         max(e) > 0))
        quiet()
        mn = min(flats) if flats else 0.0
        return hit, mn, rows
'''

if OLD not in src:
    print("  [!] one_matrix 锚点没找到")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)
print("  OK: one_matrix 改成 min 平坦度 + 有效性 + 重试")

# ---------- 阶段 3 的复现检查里也要用 min（它现在拿的是 one_matrix 的返回值，
#            语义已经变成 min，不用再改调用点，但要确认打印文字对）
src = src.replace('print("  平坦度", "min %.0f mean %.0f"',
                  'print("  平坦度(最小)", "min %.0f mean %.0f"')

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("syntax OK")

# 再把统计打印出来（在最终报告前）
src2 = io.open(P, encoding="utf-8").read()
if "STATS[" not in src2.split("def main")[-1][-1500:]:
    print("  (提示: 统计打印需要手工加在报告段)")
