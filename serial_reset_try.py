#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serial_reset_try.py —— 试着用串口的 DTR/RTS 把板子复位

★ 为什么试这个
--------------
板子 poweroff 之后是 halt 状态：PS 停了、UART 静默，但**电源还在**
（用户说得对 —— 没按按键不可能真断电）。

很多开发板把 USB 串口芯片的 DTR / RTS 接到了：
  · 复位脚（RESET / PS_POR）
  · 启动模式选择脚
  · 或至少接到一个三极管做的自动复位电路

所以「拉一下 DTR/RTS」有可能直接把板子复位起来。
即使不接复位脚，这么做也不会有任何损坏 —— DTR/RTS 只是串口的两个控制信号。

顺便监视串口输出：如果板子复位了，会看到 U-Boot / kernel 日志刷出来。

用法:
    python serial_reset_try.py [COM口]
"""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("需要 pyserial")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"


def watch(ser, secs, tag):
    """读一会儿，看有没有输出"""
    got = b""
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d = ser.read(8192)
        except Exception as e:
            print("   [%s] 读错: %s" % (tag, e))
            return got
        if d:
            got += d
        time.sleep(0.02)
    if got:
        print("   [%s] ★ 收到 %d 字节:" % (tag, len(got)))
        print("      " + got.decode("utf-8", errors="replace")
              .replace("\n", "\n      ")[:2000])
    else:
        print("   [%s] 0 字节" % tag)
    return got


def main():
    print("=" * 74)
    print(" 用 DTR/RTS 尝试复位板子   port=%s" % PORT)
    print("=" * 74)

    try:
        ser = serial.Serial(PORT, 115200, timeout=0.3)
    except Exception as e:
        sys.exit("打不开 %s: %s" % (PORT, e))

    total = 0

    # ---------- 先看看现在有没有东西 ----------
    print("\n【0】复位前先观察 3 秒")
    total += len(watch(ser, 3, "复位前"))

    # ---------- 各种 DTR/RTS 组合 ----------
    patterns = [
        ("RTS 脉冲 (拉低 200ms 再放)", lambda s: _pulse(s, "rts")),
        ("DTR 脉冲 (拉低 200ms 再放)", lambda s: _pulse(s, "dtr")),
        ("DTR+RTS 同时脉冲", lambda s: _pulse(s, "both")),
        ("esptool 风格序列 (DTR=1,RTS=0 -> RTS=1 -> DTR=0)", _esptool_seq),
        ("反相 esptool 序列", _esptool_seq_inv),
        ("DTR 翻转 10 次", lambda s: _toggle(s, "dtr", 10)),
        ("RTS 翻转 10 次", lambda s: _toggle(s, "rts", 10)),
        # ★ 加上更长的拉低时间 —— 有些复位电路需要 >500ms
        ("RTS 长拉低 1.5 秒", lambda s: _pulse(s, "rts", 1.5)),
        ("DTR 长拉低 1.5 秒", lambda s: _pulse(s, "dtr", 1.5)),
        ("DTR+RTS 长拉低 1.5 秒", lambda s: _pulse(s, "both", 1.5)),
    ]

    for name, fn in patterns:
        print("\n【尝试】%s" % name)
        try:
            fn(ser)
        except Exception as e:
            print("   执行出错: %s" % e)
        # 复位后应该会开始刷启动日志
        got = watch(ser, 6, name)
        total += len(got)
        if len(got) > 20:
            print("   ★★★ 有输出！板子可能复位了 —— 停止后续尝试")
            # 再多读一会儿，把完整启动日志抓下来
            total += len(watch(ser, 20, "启动日志续"))
            break

    # ---------- 最后再观察 ----------
    print("\n【收尾】再观察 8 秒")
    total += len(watch(ser, 8, "收尾"))

    ser.close()

    print()
    print("=" * 74)
    print(" 总共收到 %d 字节" % total)
    print("=" * 74)
    if total == 0:
        print(" ★ DTR/RTS 也没能复位板子")
        print("   ⇒ 说明这块板的复位脚没有接到串口控制线上")
        print("   ⇒ 只能按板上按键 / 重新上电")
        print()
        print("   （但至少确认了：板子电源还在，不是断电 —— 你判断是对的）")
    else:
        print(" ★ 板子有反应！看上面的日志判断它到哪一步了")


def _pulse(ser, which, hold=0.2):
    if which in ("rts", "both"):
        ser.rts = True
        time.sleep(hold)
        ser.rts = False
    if which in ("dtr", "both"):
        ser.dtr = True
        time.sleep(hold)
        ser.dtr = False
    time.sleep(0.3)


def _toggle(ser, which, n):
    for _ in range(n):
        if which == "dtr":
            ser.dtr = not ser.dtr
        else:
            ser.rts = not ser.rts
        time.sleep(0.08)
    time.sleep(0.3)


def _esptool_seq(ser):
    """ESP32/esptool 常用的复位序列"""
    ser.dtr = False
    ser.rts = True
    time.sleep(0.1)
    ser.rts = False
    time.sleep(0.1)
    ser.dtr = True
    time.sleep(0.1)
    ser.dtr = False


def _esptool_seq_inv(ser):
    ser.dtr = True
    ser.rts = False
    time.sleep(0.1)
    ser.rts = True
    time.sleep(0.1)
    ser.dtr = False
    time.sleep(0.1)
    ser.rts = False


if __name__ == "__main__":
    main()
