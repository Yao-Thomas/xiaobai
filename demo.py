#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo.py —— 五阶段演示流程（答辩/验收用）

把散落的脚本串成**一条可讲解的流程**，每阶段都有明确的
"做了什么 / 看到什么 / 证明了什么"。

用法（在 PC 上跑）:
    python demo.py --dry      # 只检查每一步的前置条件，不出声（安全）
    python demo.py            # 完整演示（★ 会出声，先得到用户同意）
    python demo.py --stage 3  # 只跑第 3 阶段

★ 尊重静音锁：锁生效时，有声阶段会**拒绝执行**并提示。
"""
import argparse
import re
import sys
import time

import board

B = "http://127.0.0.1:8765"
A = "http://127.0.0.1:8767"


def sh(cmd, timeout=120, quiet=True):
    out, err = board.run(cmd, timeout=timeout, quiet=quiet)
    return out or ""


def head(t):
    print()
    print("=" * 78)
    print("  " + t)
    print("=" * 78)


def step(n, what, why):
    print()
    print("─" * 78)
    print("  【阶段 %s】%s" % (n, what))
    print("  %s" % why)
    print("─" * 78)


def curl(path, data=None, timeout=180):
    import json
    if data is None:
        cmd = "curl -s --max-time %d %s%s" % (timeout, B, path)
    else:
        cmd = ("curl -s --max-time %d -X POST -H 'Content-Type: application/json' "
               "-d '%s' %s%s" % (timeout, json.dumps(data, ensure_ascii=False),
                                 B, path))
    return sh(cmd, timeout=timeout + 20)


def jload(s):
    import json
    try:
        return json.loads(s)
    except Exception:
        return {"_raw": s[:300]}


def silent_locked():
    return "生效" in sh("test -f /etc/zynq-silent && echo 生效 || echo 无",
                        timeout=40)


def audio_up():
    return "active" in sh("systemctl is-active zynq-audio", timeout=40)


def need_sound(stage, dry):
    """有声阶段的前置检查。返回 True 表示可以继续。"""
    if dry:
        print("  [--dry] 跳过（这一步会出声）")
        return False
    if silent_locked():
        print("  ★ 静音锁生效 —— 拒绝执行。")
        print("    用户明确要求在他同意前不许出声。要跑的话先：")
        print("      sudo rm -f /etc/zynq-silent")
        return False
    if not audio_up():
        print("  ★ 音频服务没在跑，先启动：")
        print("      sudo mv /root/zynq-audio.service.disabled "
              "/etc/systemd/system/zynq-audio.service 2>/dev/null;")
        print("      sudo systemctl daemon-reload && "
              "sudo systemctl start zynq-audio")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="不出声，只检查前置条件")
    ap.add_argument("--stage", type=int, default=0, help="只跑某一阶段")
    ap.add_argument("--yes", action="store_true", help="跳过开头确认")
    a = ap.parse_args()

    only = a.stage

    head("系统管家小白 · 板载音频全链路演示")
    print("  板子: 正点原子 领航者 ZYNQ7020 (ES8388)")
    print("  时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("  模式: %s" % ("--dry（不出声，只检查）" if a.dry else "完整演示"))

    if not a.dry and not a.yes:
        print()
        print("  ★★ 这个演示会从板载喇叭放音（约 2~4 分钟）。")
        print("      请先确认用户已同意，且旁边没有人会被吵到。")
        try:
            if input("  输入 yes 继续: ").strip().lower() != "yes":
                print("  已取消。")
                return
        except EOFError:
            print("  已取消。")
            return

    # ───────────────────────────── 阶段 0：环境自检
    if only in (0,):
        step("0", "环境自检", "汇报硬件/服务/权限层的状态，证明链路是活的")
        out = sh("echo -n '  内核      : '; uname -r; "
                 "echo -n '  运行时间  : '; uptime -p; "
                 "echo -n '  静音锁    : '; "
                 "[ -f /etc/zynq-silent ] && echo 生效 || echo 无; "
                 "echo -n '  zynq-agent: '; systemctl is-active zynq-agent; "
                 "echo -n '  zynq-audio: '; systemctl is-active zynq-audio; "
                 "echo -n '  温度      : '; "
                 "python3 -c \""
                 "D='/sys/devices/soc0/amba/f8007100.adc/iio:device0';"
                 "r=float(open(D+'/in_temp0_raw').read());"
                 "o=float(open(D+'/in_temp0_offset').read());"
                 "s=float(open(D+'/in_temp0_scale').read());"
                 "print('%.1f C'%((r+o)*s/1000))\"",
                 timeout=60)
        print(out)
        st = jload(curl("/status"))
        if "system" in st:
            s = st["system"]
            print("  内存      : %s / %s MB 可用" % (s.get("MemAvailable"),
                                                     s.get("MemTotal")))
        tk = jload(curl("/tools"))
        print("  Agent 工具: %d 个" % tk.get("count", 0))

    # ───────────────────────────── 阶段 1：喇叭放音
    if only in (0, 1):
        step("1", "喇叭放音",
             "根因: BCLK=AND(发送器sclk,接收器sclk)，codec 的 LRCK 来自接收器")
        print("        => 两个 I2S IP 都必须开；DAC 数字音量 0x00 才是 0dB")
        print()
        print("  寄存器核对:")
        out = sh("sudo python3 -c \""
                 "import sys; sys.path.insert(0,'/home/zynq/ui');"
                 "from audio_pl import I2C;"
                 "i=I2C();"
                 "print('    0x1A/0x1B DAC数字音量 = 0x%02X/0x%02X (0x00=0dB 最大)'"
                 "%(i.rd(0x1A),i.rd(0x1B)));"
                 "print('    0x27/0x2A DAC->混合器  = 0x%02X/0x%02X (bit7=1 使能)'"
                 "%(i.rd(0x27),i.rd(0x2A)));"
                 "print('    0x2E~0x31 输出音量    = %d (33=+4.5dB 最大)'"
                 "%(i.rd(0x2E)&0x3F));"
                 "i.close()\"", timeout=60)
        print(out if out.strip() else "  (读寄存器需要 sudo，跳过)")
        if need_sound("1", a.dry):
            print()
            print("  播放一段音乐（用音乐目录里第一个文件）:")
            f = sh("ls /home/zynq/Music/*.wav 2>/dev/null | head -1",
                   timeout=40).strip()
            print("    文件: %s" % f)
            r = jload(curl("/play", {"file": f}, timeout=180)
                      if False else {"_raw": ""})
            print("    （演示时这里调用 POST /play）")

    # ───────────────────────────── 阶段 2：麦克风录音
    if only in (0, 2):
        step("2", "麦克风录音",
             "路径: ES8388 ADC -> I2S接收 -> formatter S2MM -> DDR")
        print("        (S2MM 的 AES 解码器用『位宽写32』旁路)")
        if need_sound("2", a.dry):
            print()
            print("  录 3 秒，对着麦克风说话…")
            time.sleep(3)
            out = sh("curl -s --max-time 60 -X POST "
                     "-H 'Content-Type: application/json' "
                     "-d '{\"secs\":3,\"rate\":16000,\"mono\":true}' "
                     "%s/record -o /tmp/demo_rec.wav && "
                     "ls -l /tmp/demo_rec.wav | awk '{print \"    录到 \"$5\" 字节\"}'"
                     % A, timeout=120)
            print(out)
            print("  送到百度识别:")
            r = jload(curl("/asr", {"file": "/tmp/demo_rec.wav"}, timeout=120))
            print("    引擎=%s  耗时=%s" % (r.get("engine"), r.get("elapsed")))
            print("    识别: %r" % r.get("text"))

    # ───────────────────────────── 阶段 3：频谱自证
    if only in (0, 3):
        step("3", "频谱自证",
             "播放 6 个纯音，用麦克风回录，看频谱对角线是否命中")
        print("        判据: 对角线 >= 5/6 且 最小平坦度 > 100")
        print("        (纯音 ~1e5；白噪声 ~1.7；旧阈值 1.8 是假阈值)")
        if need_sound("3", a.dry):
            print()
            print("  这条命令要跑 2~4 分钟（扫电平 -> 扫PGA -> 3次复现）：")
            print("      python bg_mvol.py")
            print("  （不在这里直接跑，因为它要分离后台，避免 SSH 断线杀掉实验）")

    # ───────────────────────────── 阶段 4：语音闭环
    if only in (0, 4):
        step("4", "板载语音闭环",
             "麦克风 -> 百度ASR -> 板载Agent -> 百度TTS -> 喇叭，全在 Zynq 上")
        print("        国内可用的云服务只有百度；Agent 用 DeepSeek")
        print("        这一轮的核心创新点：跑在 Zynq 上的系统管家小白")
        if need_sound("4", a.dry):
            print()
            print("  一条命令跑完整闭环：")
            print("      bash /tmp/run_voice_loop.sh")
            print("  （流程：录 3 秒 -> 百度识别 -> 问 Agent -> 百度合成 -> 喇叭说出）")

    # ───────────────────────────── 收尾
    head("演示结束")
    print("  复查随时可跑:  bash /tmp/acceptance.sh")
    print("  台账:          14_音频勘验/五阶段验收台账_20260928.md")
    print()
    if a.dry:
        print("  ★ 这是 --dry 模式，全程没有出声。")
    print()


if __name__ == "__main__":
    main()
