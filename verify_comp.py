#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_comp.py —— 客观验证色温补偿有没有真的进到显存

════════════════════════════════════════════════════════════════════
为什么需要（也是这几轮来回的根因）
════════════════════════════════════════════════════════════════════
用户反复说"效果没出来""你看到的和我看到的不一样"。

根因：我一直用【读 /dev/fb0】的方式来"看"屏幕。
      但显示链路上有两段：
          设计色 --ColorDraw补偿--> 显存 --面板--> 人眼
      我的截图停在中间那一环（显存），
      而用户看的是最后那一环（经过面板）。
      ★ 面板有色偏 ⇒ 这两者本来就不可能一致。

所以"效果有没有出来"不能靠我看图判断，必须客观测：
    读显存里的实际像素值，和"设计值 + 预期补偿"对比。
    对得上 = 补偿真的生效了（用户那边看到的是不是满意，另说）。

用法（板子，root）:
    sudo python3 /home/zynq/verify_comp.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq/ui")

W, H, STRIDE, VH = 1024, 600, 3072, 1200


def rd(p, d=""):
    try:
        return open(p).read().strip()
    except Exception:
        return d


def main():
    yoff = 0
    try:
        yoff = int(rd("/sys/class/graphics/fb0/pan", "0,0").split(",")[1])
    except Exception:
        pass

    f = open("/dev/fb0", "rb")
    f.seek(yoff * STRIDE)
    raw = f.read(STRIDE * H)

    def px(x, y):
        o = y * STRIDE + x * 3
        return (raw[o], raw[o + 1], raw[o + 2])

    print("=" * 70)
    print(" 色温补偿客观验证")
    print("=" * 70)
    print("  当前显示页 yoff = %d" % yoff)
    print()

    # ── ① 补偿函数本身对不对 ──
    import fbui
    scr = fbui.Screen()
    print("  ① comp_color() 的输出（这是纯粹的函数检查）：")
    for col in [(10, 12, 22), (18, 22, 34), (30, 96, 168), (24, 29, 44),
                (255, 255, 255), (0, 0, 0)]:
        print("     设计 %-18s -> 补偿后 %s" % (str(col), str(scr.comp_color(col))))
    print("     （蓝通道应该减 12 左右；0 不变；255 变 240）")
    print()

    # ── ② 显存里实际是什么 ──
    print("  ② 显存里实际采样（『补偿真的写进去了吗』）：")
    print("     %-22s %-20s %s" % ("位置", "显存实测 RGB", "和设计值比"))
    samples = [
        ("背景/角落", 500, 200, (10, 12, 22)),
        ("左侧栏", 60, 320, (18, 22, 34)),
        ("桌面卡片", 300, 150, None),
        ("底部任务栏", 500, 575, None),
    ]
    for name, x, y, design in samples:
        got = px(x, y)
        if design:
            d = "设计 %s  ΔB=%+d" % (str(design), got[2] - design[2])
        else:
            d = "-"
        print("     %-22s %-20s %s" % (name, str(got), d))
    print()

    # ── ③ 结论 ──
    bg = px(500, 200)
    # 桌面首页在这里可能不是 App 的背景色，所以只做一个粗略判断
    print("  ③ 判断：")
    print("     · 如果 ① 里蓝通道确实减了 12 → 补偿函数 OK")
    print("     · 如果 ② 里显存的蓝值比设计低 ~12 → 补偿真的写进显存了")
    print("     · ★ 两者都 OK 但用户仍觉得偏蓝")
    print("       ⇒ 说明 12 这个补偿量【不够】，需要加大")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
