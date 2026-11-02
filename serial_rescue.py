#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serial_rescue.py —— 判决板子到底是"停机"还是"真断电"，并尝试唤醒

★ 为什么上一版探测不准
----------------------
板子 poweroff 之后是 **halt** 状态：PS 停止、kernel 挂起、getty 被杀。
所以：
  · 串口**不会有回显**（没人读键盘输入了）—— 我上次读到 0 字节就以为断电了
  · 但**电源还在**，PL 还配着，CH340 也活着
⇒ 0 字节 ≠ 断电。这个判断错了。

本脚本要区分三种情况：
  A. 真断电       -> 串口完全静默，且**连 BREAK 也没反应**
  B. 停机(halt)   -> 静默，但发 BREAK/大量回车有时能触发点东西
  C. 在重启循环   -> 会持续看到 U-Boot / kernel 日志

做法：
  1. 先静默读 5 秒（看有没有自发输出）
  2. 敲大量回车
  3. 发 BREAK（串口线的 TX 拉低 250ms 以上）—— 有些 bootloader 会因此进下载模式
  4. 换个波特率再试（115200 / 1500000 / 9600）
  5. 全程记录收到的字节

用法:
    python serial_rescue.py [COM口]
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


def collect(ser, secs, tag):
    total = 0
    chunks = []
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d = ser.read(4096)
        except Exception as e:
            print("   [%s] 读错误: %s" % (tag, e))
            break
        if d:
            total += len(d)
            chunks.append(d)
        time.sleep(0.03)
    if total:
        raw = b"".join(chunks)
        print("   [%s] 收到 %d 字节:" % (tag, total))
        print("      " + raw.decode("utf-8", errors="replace").replace("\n", "\n      ")[:1500])
    else:
        print("   [%s] 0 字节" % tag)
    return total


def main():
    print("=" * 74)
    print(" 串口救援判决：停机 还是 断电？   port=%s" % PORT)
    print("=" * 74)

    try:
        ser = serial.Serial(PORT, 115200, timeout=0.3)
    except Exception as e:
        sys.exit("★ 打不开 %s: %s\n  （XCOM 等工具是不是占着？）" % (PORT, e))

    grand = 0

    print("\n【1】静默观察 6 秒（看有没有自发输出，比如重启日志）")
    grand += collect(ser, 6, "静默")

    print("\n【2】猛敲回车 30 次（如果有 shell，会出提示符）")
    for _ in range(30):
        ser.write(b"\r\n")
        time.sleep(0.05)
    grand += collect(ser, 4, "回车后")

    print("\n【3】发 Ctrl-C / Ctrl-D（万一卡在某个前台进程）")
    for k in (b"\x03", b"\x04", b"\x1c"):
        ser.write(k)
        time.sleep(0.4)
    grand += collect(ser, 3, "Ctrl-C/D 后")

    print("\n【4】★ 发 BREAK（TX 拉低 300ms）—— 有些 bootloader 认这个")
    try:
        ser.break_condition = True
        time.sleep(0.3)
        ser.break_condition = False
        print("   BREAK 已发")
    except Exception as e:
        print("   发 BREAK 失败: %s" % e)
    for _ in range(10):
        ser.write(b"\r\n")
        time.sleep(0.08)
    grand += collect(ser, 8, "BREAK 后")

    print("\n【5】换波特率试（1500000 / 9600 / 57600）")
    for br in (1500000, 9600, 57600):
        try:
            ser.baudrate = br
            time.sleep(0.3)
            for _ in range(10):
                ser.write(b"\r\n")
                time.sleep(0.06)
            n = collect(ser, 3, "波特率 %d" % br)
            grand += n
        except Exception as e:
            print("   波特率 %d 失败: %s" % (br, e))
    ser.baudrate = 115200

    print("\n【6】再最后观察 8 秒")
    grand += collect(ser, 8, "收尾")

    ser.close()

    print()
    print("=" * 74)
    print(" 总共收到 %d 字节" % grand)
    print("=" * 74)
    if grand == 0:
        print(" ★ 串口全程完全静默（连 BREAK 都没反应）")
        print()
        print("   这说明：PS 已经 halt，没有 U-Boot、没有 kernel、没有 getty。")
        print("   ★ 但注意：这不代表断电！halt 状态下串口本来就是静默的。")
        print()
        print("   ⇒ 要恢复只有两条路：")
        print("       1) 按板子上的复位键 / 重新上电（你的原话）")
        print("       2) 如果板子接了 JTAG，可以从 JTAG 复位（现在没有）")
    else:
        print(" ★ 串口有反应！板子还活着（可能刚重启或进了 U-Boot）")
        print("   ⇒ 可以试着从串口把它拉起来")


if __name__ == "__main__":
    main()
