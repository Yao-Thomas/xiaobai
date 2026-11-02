#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_kb.py —— ★ 把板子的【实时状态】变成可检索的知识块

════════════════════════════════════════════════════════════════════
为什么这个是我们独有、AI 负责人做不了的
════════════════════════════════════════════════════════════════════
AI 负责人交付的 RAG 知识库是【静态的项目文档】：
    536 个 chunk，来自 11 篇文档 + 源码 docstring
它能回答"CNN 的量化公式是什么"、"ES8388 的寄存器在哪"。

但它回答不了【关于板子自己此刻的问题】：
    "最近温度怎么样"      → 需要温度历史
    "我改过几次 FPGA"     → 需要变更记录
    "现在服务都正常吗"    → 需要 systemd 状态
    "上次采集的波形是什么" → 需要采集记录

⇒ 这一层只有【住在板子里】的 agent 能做。这就是"板载自主助手"的核心。

════════════════════════════════════════════════════════════════════
做法
════════════════════════════════════════════════════════════════════
把实时数据渲染成【和 chunks.jsonl 同样格式】的条目：
    {"text": "...", "source": "...", "title_path": "..."}
写到 /home/zynq/agent/kb/live_chunks.jsonl

然后 RagModel 把它和静态知识库一起加载（见 tiers.py 的修改）。
这样：
    · 静态问题 → 检索到项目文档
    · 动态问题 → 检索到实时状态
    用的是同一套 BM25，不用改检索算法。

★ 刷新时机：每次 agent 启动时刷新一次；
  另外加了个 --watch 模式可以定时刷新（默认 60 秒）。

用法（板子上）:
    sudo python3 live_kb.py                # 生成一次
    sudo python3 live_kb.py --show         # 生成并打印出来看看
    sudo python3 live_kb.py --watch 60     # 每 60 秒刷新
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# ★ 写到哪里？
#
# 踩过：live_kb.py 放在 /home/zynq/ 下，所以自然的写法是
#   KB_DIR = HERE/kb  →  /home/zynq/kb/
# 但 agent 读的是 【/home/zynq/agent/kb/】（和它的 rag.py 同目录）。
# ⇒ 结果 systemd 的 ExecStartPre 每次都在刷新一个没人读的文件，
#   agent 用的还是旧的实时块（问"服务都正常吗"答的是陈旧的）。
#
# 现在：优先写 agent 的 kb 目录（存在的话），否则退回 HERE/kb。
_AGENT_KB = os.path.join(HERE, "agent", "kb")
KB_DIR = _AGENT_KB if os.path.isdir(_AGENT_KB) else os.path.join(HERE, "kb")
OUT = os.path.join(KB_DIR, "live_chunks.jsonl")

# ★ 「问题示例」行的标记 —— 检索要用它，但回答里要滤掉
#   （tiers.py 的 RagModel.answer() 会按这个前缀过滤）
HINT_MARK = "【本块回答这类问题】"


def _sh(cmd, timeout=8):
    """跑一条命令，返回 stdout（失败返回空串）"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def chunk(text, source, title="实时状态", asks=()):
    """造一个知识块

    ★★ asks 是【问题说法】，这个很关键，不是装饰。

    AI 负责人的静态知识库是从文档按标题切出来的，标题本身就是问题
    （"ES8388 的 DAC 音量寄存器是多少"），所以用户怎么问都能对上 bigram。

    而我们的实时块是【渲染出来的叙述】，没有"问题"这个维度。
    实测踩过：问"我改过几次 FPGA"，块里写的是"变更记录"——
    中文 bigram 分词下 改过/过几/几次 和 变更/更记/记录 零重叠，
    检索直接落空，agent 就拒答了。

    ★ 试过两种方案，都翻车：
      ① 在末尾追加 "常见问法：xxx" —— 检索命中了，但回答里混进噪音
      ② 用标记行 + 在 answer() 里过滤 —— 抽取器会把标记行和正文
         拼成一个句子，按句号切的时候把正文第一句也删了，
         回答变成 "根据项目资料： 来源：live:xxx"
      ⇒ 最终方案：把问法写成正文里【自然的第一句】。
        既让 bigram 有东西匹配，又不需要过滤。
    """
    if asks:
        # 一行自然的话，把问法嵌进去
        text = ("关于「" + "」「".join(asks) + "」这类问题，"
                + text.strip())
    return {"text": text.strip(), "source": source, "title_path": title}


# ══════════════════════════════════════════════════════════════════
#  各类实时数据的渲染
# ══════════════════════════════════════════════════════════════════
def c_system():
    """系统信息（uptime / 内存 / 磁盘 / 内核）"""
    out = []
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        h, m = int(up // 3600), int((up % 3600) // 60)
        out.append("开机时长 %d 小时 %d 分钟（%.0f 秒）" % (h, m, up))
    except Exception:
        pass
    try:
        mi = {}
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":", 1)
            mi[k] = int(v.strip().split()[0])
        tot = mi.get("MemTotal", 0) // 1024
        avail = mi.get("MemAvailable", 0) // 1024
        out.append("内存共 %d MB，当前可用 %d MB" % (tot, avail))
    except Exception:
        pass
    try:
        st = os.statvfs("/")
        tot = st.f_blocks * st.f_frsize // (1024 * 1024)
        free = st.f_bavail * st.f_frsize // (1024 * 1024)
        out.append("根分区共 %d MB，剩余 %d MB" % (tot, free))
    except Exception:
        pass
    try:
        out.append("内核 %s，主机名 %s"
                   % (os.uname().release, os.uname().nodename))
    except Exception:
        pass
    if not out:
        return None
    return chunk("板子当前的系统状态：\n  " + "\n  ".join(out)
                 + "\n问题示例：板子开了多久？内存还剩多少？磁盘还剩多少？",
                 "live:/proc", "实时状态 / 系统信息", asks=("内存还剩多少", "磁盘还剩多少空间", "板子开了多久"))


def c_thermal():
    """温度（当前 + 最近统计）"""
    temps = []
    # 优先读历史文件
    #
    # ★ 这里踩过一次：history.txt 的行格式是
    #       "23:26:40 85.0 OK"
    #   我一开始用 re.search(r"([\d.]+)") 抓【第一个】数字 ——
    #   结果抓到时间的小时 "23"，温度显示成 23.0 °C。
    #   ⇒ 现在显式跳过 HH:MM:SS 前缀再抓。
    pat = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}\s+([\d.]+)")
    pat2 = re.compile(r"([\d.]+)\s*(?:OK|WARN|HOT|CRIT|°|C)\b")
    for p in ("/run/thermal/history.txt", "/var/log/thermal_history.txt"):
        try:
            with open(p) as f:
                lines = f.readlines()[-200:]
            got = []
            for ln in lines:
                m = pat.match(ln) or pat2.search(ln)
                if m:
                    try:
                        v = float(m.group(1))
                    except Exception:
                        continue
                    # 合理范围过滤（板子不会到 0 度以下或 150 度以上）
                    if 10.0 <= v <= 150.0:
                        got.append(v)
            if got:
                temps = got
                break
        except Exception:
            continue
    # 读不到历史就读一次即时值
    if not temps:
        try:
            sys.path.insert(0, HERE)
            import thermal_guard as TG
            for n in ("read_temp", "get_temp", "temp_now"):
                if hasattr(TG, n):
                    v = getattr(TG, n)()
                    if v:
                        temps.append(float(v))
                        break
        except Exception:
            pass
    if not temps:
        return None
    cur = temps[-1]
    mn, mx, avg = min(temps), max(temps), sum(temps) / len(temps)
    # 门槛（和 thermal_guard.py 保持一致）
    thr = "正常（< 85）" if cur < 85 else (
        "偏高（85~90，守护会降载）" if cur < 90 else "过温（≥ 90）")
    txt = ("板子温度：当前 %.1f °C，最近 %d 次采样里最低 %.1f °C、"
           "最高 %.1f °C、平均 %.1f °C，判定为%s。\n"
           "★ 这块 Zynq-7020 满载容易上 85~90 °C，所以有 thermal-guard 守护："
           "超过阈值会降载，冷却后自动恢复；"
           "★ 注意 poweroff 是单向的（关了就起不来），冷却只用 systemctl reboot。"
           % (cur, len(temps), mn, mx, avg, thr))
    return chunk(txt, "live:thermal", "实时状态 / 温度", asks=("板子现在温度多少", "温度高不高", "会不会过热"))


def c_services():
    """systemd 服务状态"""
    svcs = ("zynq-desktop", "zynq-audio", "zynq-agent", "thermal-guard",
            "thermal-cooldown", "cloud-api", "zynq-gpu-loader")
    lines = []
    for s in svcs:
        st = _sh("systemctl is-active %s 2>/dev/null" % s) or "unknown"
        lines.append("%s=%s" % (s, st))
    txt = ("板子上常驻服务状态：\n  " + "\n  ".join(lines)
           + "\n各个服务的作用：zynq-desktop 卡片式桌面；zynq-audio 音频；"
             "zynq-agent 系统管家小白（8765）；thermal-guard 温度守护；"
             "thermal-cooldown 冷却重启；cloud-api 云协同（8768）。")
    return chunk(txt, "live:systemd", "实时状态 / 服务", asks=("服务都正常吗", "有哪些服务在跑", "agent 在运行吗"))


def c_changes():
    """FPGA 变更记录

    ★ 用 CLI 而不是 import 模块：
      hw_change.py 是给 agent 当工具用的，内部结构可能变；
      但它有个稳定的命令行入口 `python3 hw_change.py --list`。
      踩过：一开始猜了 list_changes/changes/load_all 这些函数名，
      一个都不存在，于是"我改过几次 FPGA"永远答不出来。
    """
    script = os.path.join(HERE, "agent", "hw_change.py")
    if not os.path.exists(script):
        script = os.path.join(HERE, "hw_change.py")
    if not os.path.exists(script):
        return None
    out = _sh("%s %s --list 2>/dev/null" % (sys.executable, script), timeout=15)
    if not out:
        return chunk("板子还没有任何 FPGA 变更记录。\n"
                     "变更流程：hw_hdl_edit 改 RTL（自动备份+语法检查）"
                     "→ hw_fpga_build 提交综合（PC 侧守护跑 Vivado）"
                     "→ hw_flash_bitstream 刷流 → hw_verify 跑回归 "
                     "→ 不对就 hw_change_rollback 回滚。",
                     "live:hw_change", "实时状态 / FPGA 变更", asks=("我改过几次 FPGA", "最近改了什么", "变更记录有哪些"))
    lines = [ln for ln in out.splitlines() if ln.strip()]
    head = lines[:12]
    txt = ("板子最近的 FPGA 变更记录（共 %d 行）：\n  %s\n"
           "★ 变更流程：hw_hdl_edit 改 RTL（自动备份+语法检查）"
           "→ hw_fpga_build 提交综合 → hw_flash_bitstream 刷流 "
           "→ hw_verify 跑回归 → 不对就 hw_change_rollback 回滚。"
           % (len(lines), "\n  ".join(head)))
    return chunk(txt, "live:hw_change", "实时状态 / FPGA 变更", asks=("我改过几次 FPGA", "最近改了什么", "变更记录有哪些"))


def c_scope():
    """示波器状态"""
    txt = ("板载示波器：IP scope_cap_axi 在 0x43CC0000，"
           "4096 点 × 8 bit 双 bank BRAM，采样率 = 100 MHz / DIV，"
           "DIV=5 时 20 MSPS，支持触发/预触发。\n"
           "★ 当前信号源是【板子内部 DDS】（可以自己发正弦/方波/三角/锯齿，"
           "频率任意），外部 XADC 通路代码里预留了（capture_once(src=1)）"
           "但硬件还没接。\n"
           "★ 内部 DDS 的更新率是固定的，所以 DEC 越大波形台阶越粗 —— "
           "演示时建议小 DEC + 高频率（比如 20 kHz + DEC=1），"
           "这样能拿到 4 个以上周期，波形识别才准。\n"
           "毛刺检测属于 PL 硬件检测器（100 MHz / 10 ns 分辨率），"
           "CPU 采样抓不到 ns 级毛刺。")
    return chunk(txt, "live:scope", "实时状态 / 示波器", asks=("示波器采样率是多少", "能测外部信号吗", "信号从哪来"))


def c_cnn():
    """CNN / AI 能力现状（跑出来的真实数字）"""
    txt = ("板载 AI 能力现状：\n"
           "① 波形识别：PL 上的 CNN 加速器（cnn_conv_pool @0x43CD0000 + "
           "cnn_fc @0x43CE0000），输入 28×28 int8 密度图，"
           "逐层 MFQ 是 201 / 371 / 1390，输出 8 类"
           "（sine/square/triangle/sawtooth/noise/clipping/"
           "signal_loss/duty_abnormal）。\n"
           "   ★ 上板实测：交付包 reference 512/512 点逐位一致；"
           "端到端（4096 点波形→wdens→PL）95.3%（122/128）。\n"
           "② 示波器自动设置 RL：74 维观测 → 触发电平/时基/增益，"
           "上板 32/32 逐位一致，RL 训练成绩 11% → 92.2%。\n"
           "③ 音频 EQ 调优 RL：16 维观测 → 8 段增益，上板 32/32 逐位一致。\n"
           "④ 本地 RAG：静态知识块（项目文档）加实时状态块一起检索，"
           "纯标准库 BM25 + 中文 bigram，断网也能答。\n"
           "⑤ 云端：DeepSeek（deepseek-chat），分级推理 auto 模式下"
           "云端不通会自动降级到本地 RAG。\n"
           "★ 单次波形识别约 11.5 ms（含 flush），比 CPU 纯 Python 复刻"
           "（约 800 ms）快约 70 倍。")
    return chunk(txt, "live:ai", "实时状态 / AI 能力", asks=("AI 能做什么", "波形识别准不准", "断网还能用吗"))


def c_hw():
    """硬件资源"""
    txt = ("板子硬件资源：正点原子 领航者 ZYNQ7020 V3.9，"
           "芯片 xc7z020clg400-2（双核 Cortex-A9 + FPGA），"
           "1 GB DDR3，SD 卡启动，Ubuntu 20.04 armv7l。\n"
           "PL 里挂的自研 IP 地址表："
           "lcd_id=0x41200000，pwm_backlight=0x43C00000，"
           "clk_wiz=0x43C30000，v_frmbuf_wr=0x43C40000，"
           "audio_formatter=0x43C50000，i2s_rx=0x43C60000，"
           "i2s_tx=0x43C70000，clk_wiz_dyn=0x43C80000，"
           "hdmi_vtc=0x43C90000，v_frmbuf_rd=0x43CA0000，"
           "gpu_0=0x43CB0000，scope_0=0x43CC0000，"
           "cnn_conv_pool=0x43CD0000，cnn_fc=0x43CE0000。\n"
           "★ 开机预留了 0x3E000000~0x3FFFFFFF（32 MB）给 PL 做 DMA 缓冲，"
           "这块内存不走 CPU 缓存，避免了一致性问题"
           "（bootargs 里 mem=992M）。\n"
           "音频编解码是 ES8388，采集只能用 S24_LE 格式，"
           "而且 24 位数据没有符号扩展，要自己从第 23 位扩展。")
    return chunk(txt, "live:hw", "实时状态 / 硬件", asks=("板子什么型号", "芯片是什么", "PL 里有哪些 IP"))


BUILDERS = (c_system, c_thermal, c_services, c_changes,
            c_scope, c_cnn, c_hw)


def build():
    out = []
    for fn in BUILDERS:
        try:
            c = fn()
            if c:
                out.append(c)
        except Exception as e:
            print("  [live_kb] %s 失败: %s" % (fn.__name__, e))
    return out


def save(chunks, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--watch", type=int, default=0,
                    help="每 N 秒刷新一次（0=只跑一次）")
    a = ap.parse_args()

    while True:
        t0 = time.time()
        chunks = build()
        p = save(chunks)
        n = sum(len(c["text"]) for c in chunks)
        print("[%s] 实时知识块 %d 个，共 %d 字 → %s（%.0f ms）"
              % (time.strftime("%H:%M:%S"), len(chunks), n, p,
                 (time.time() - t0) * 1000))
        if a.show:
            print()
            for c in chunks:
                print("─" * 70)
                print("【%s】  source=%s" % (c["title_path"], c["source"]))
                print(c["text"][:500])
                print()
        if a.watch <= 0:
            break
        time.sleep(a.watch)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
