#!/bin/bash
# codec_reset.sh —— 把 ES8388 恢复成"能出声"的正常状态
#
# ══════════════════════════════════════════════════════════════════
#  为什么需要这个
# ══════════════════════════════════════════════════════════════════
# 2026-09-28：静默实验（silent_play_test.py）为了"放音但没声音"，
# 把 DAC 数字音量寄存器 0x1A/0x1B 写成了 0xC0 = -96dB 静音。
# 实验结束后它**没有恢复**（当时是故意的，为了多重保险）。
#
# 后果：如果之后直接启动音频服务放音，codec 还是静音的 ——
#       会表现为"服务正常、寄存器全对、但一点声音都没有"，
#       非常容易误判成硬件故障。
#
# 这个脚本把关键寄存器恢复成能出声的状态。
#   ★ 它本身不播放任何东西，但恢复之后**下一次播放会出声**。
#     所以要在用户同意放音之后再跑，或者跟 start 音频服务一起跑。
#
# 用法:  sudo bash codec_reset.sh
#        sudo bash codec_reset.sh --check    只读，看当前状态

FLAG="${1:-}"

sudo python3 - "$FLAG" <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import I2C, es8388_set_vol
except Exception as e:
    print("  导入失败:", e)
    raise SystemExit(1)

i = I2C()
check_only = (len(sys.argv) > 1 and sys.argv[1] == "--check")

def show(tag):
    print("  %s" % tag)
    print("    0x1A/0x1B DAC数字音量 = 0x%02X/0x%02X   %s"
          % (i.rd(0x1A), i.rd(0x1B),
             "★ 静音(0xC0)" if i.rd(0x1A) == 0xC0 else "可出声"))
    print("    0x27/0x2A DAC->混合器  = 0x%02X/0x%02X   %s"
          % (i.rd(0x27), i.rd(0x2A),
             "使能" if (i.rd(0x27) & 0x80) else "★ 未使能(没声音)"))
    v = i.rd(0x2E) & 0x3F
    print("    0x2E~0x31 输出音量     = %d                 %s"
          % (v, "最小(-45dB)" if v == 0 else "+%.1f dB" % (-45 + v * 1.5)))
    print("    0x30/0x31 (走喇叭功放) = %d/%d"
          % (i.rd(0x30) & 0x3F, i.rd(0x31) & 0x3F))

show("当前状态:")
print()

if check_only:
    print("  （--check 只读，没有改动）")
    i.close()
    raise SystemExit(0)

# ---- 恢复 ----
# es8388_set_vol(i2c, 输出音量, dac_digital)
#   输出音量 33 = +4.5dB 最大；dac_digital 0 = 0dB（不静音）
es8388_set_vol(i, 33, 0)
print("  已写入: 输出音量=33(+4.5dB)  DAC数字=0(0dB)  混合器 bit7=1")
print()
show("恢复后:")
i.close()
print()
print("  ★ 注意：恢复之后**下一次播放就会出声**。")
print("    如果现在还不该出声，请先别启动音频服务，")
print("    或者跑:  sudo systemctl stop zynq-audio")
PY
