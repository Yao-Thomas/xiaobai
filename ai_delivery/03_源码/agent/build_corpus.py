"""
build_corpus.py —— 任务 D 语料构建：RAG 知识库 + LoRA 指令数据集

★ 纯标准库实现（不 import torch/transformers/numpy），可在本地 Windows 直接跑。

产出（默认写在本目录下）：
  kb/chunks.jsonl          —— RAG 知识库：按标题层级切分的 chunks
                              （每块 ~300~600 字，带 source 与 title_path 元数据）
  lora_data/train.jsonl    —— LoRA 指令微调训练集（sharegpt 风格）
  lora_data/val.jsonl      —— LoRA 指令微调验证集（从同一语料按固定种子切出）

数据来源（★ 只来自真实项目文档，不胡编）：
  · AI训练交接包(1)/ 下所有 .md
  · ai_training/docs/00_接口冻结单.md
  · ai_training/src/ 下所有 .py 的模块 docstring
  · work/prev_cnn/ 下所有 .md

LoRA 数据集由两部分构成：
  1) FACT_BANK —— 人工从上述文档逐条核对出来的事实（问题/答案/来源），
     每条事实通过少量“自然问法模板”扩充成多条指令，保证 ≥800 条。
  2) REFUSAL_BANK —— 一批“文档里没有答案”的样本（如“今天天气怎么样”），
     让模型学会说“不知道 / 不在我的知识范围内”，用于抑制幻觉。

用法：
    python build_corpus.py                          # 自动探测项目根目录并构建
    python build_corpus.py --project-root <dir>     # 显式指定项目根目录
    python build_corpus.py --out-kb <dir> --out-lora <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from typing import Dict, List, Tuple

# 让 Windows 控制台（默认 cp1252）也能正确打印中文，避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))

# 默认输出目录（相对本文件）
DEFAULT_KB = os.path.join(_HERE, "kb")
DEFAULT_LORA = os.path.join(_HERE, "lora_data")

# 文档来源根（相对项目根目录），(相对路径, 扩展名集合)
# ★ 只索引"既有"的 src 代码 docstring（common/train），不索引本包 src/agent 自身，
#   否则 build_corpus/eval/rag 自己的 docstring（含拒答样例）会污染知识库。
DOC_ROOTS = [
    ("AI训练交接包(1)", {".md"}),
    ("ai_training/docs", {".md"}),
    ("ai_training/src/common", {".py"}),   # 只取模块 docstring
    ("ai_training/src/train", {".py"}),    # 只取模块 docstring
    ("work/prev_cnn", {".md"}),
]

# ---------------------------------------------------------------------------
# ★ 事实库 FACT_BANK —— 每条都来自真实文档，q 为同一事实的多种自然问法
#   格式：{"q": ["问法1", "问法2", ...], "a": "答案", "s": "文件#标题"}
# ---------------------------------------------------------------------------
FACT_BANK: List[Dict] = [
    # ================= 一、项目整体介绍 =================
    {"q": ["系统管家小白是什么", "介绍一下这个项目"], "a": "系统管家小白是一个基于 Zynq-7020 开发板的板载自主助手，目标是把它做成一台能装软件、能上网、有图形桌面的嵌入式小电脑，并用 FPGA（PL）做图形加速。",
     "s": "AI训练交接包(1)/04_项目背景/项目总览.md#一、项目目标"},
    {"q": ["这个项目参加什么比赛", "项目的赛道是什么"], "a": "参加 2026 全国大学生嵌入式芯片与系统设计竞赛，AMD 赛道（FPGA 创新设计），自主选题。",
     "s": "AI训练交接包(1)/04_项目背景/★技术实施计划_v2_20260930.md#系统管家小白 —— 技术实施计划 v2"},
    {"q": ["板子是什么型号", "用的哪块开发板"], "a": "正点原子 领航者 ZYNQ7020（ATK-DF7010/7020P），底板 V3.9，核心板 V2.5。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"q": ["主控芯片是什么", "Zynq 芯片具体型号"], "a": "XC7Z020CLG400-2，属于 Zynq-7000 系列，双核 Cortex-A9 + FPGA。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"q": ["板子上跑什么系统", "操作系统是什么"], "a": "Ubuntu 20.04 armv7l（32 位 ARM），内核 5.4.0-xilinx-v2020.2（定制版，含 ES8388 驱动）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"q": ["板子主机名是什么", "hostname 是什么"], "a": "主机名是 zynq-board。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"q": ["项目的三大技术高点是什么", "有什么创新点"], "a": "三大技术高点：① agent 改硬件 + 自动验证 + 自动回滚；② 声学自测闭环（板子用自己的耳朵验证自己的嘴）；③ 波形 AI 分析（数据集自产 + PL 内推理）。",
     "s": "AI训练交接包(1)/04_项目背景/★技术实施计划_v2_20260930.md#1.2 三个可演示的技术高点"},
    {"q": ["三个人怎么分工", "团队怎么分工"], "a": "分三块：示波器负责人（示波器 V2、数据集自产、PL 故障检测、示波器 AI 环境侧）；AI 训练负责人（模型训练/量化/RL/云端 API）；主线融合（采集修复、声学自测、agent 硬件工具、CNN 集成、云协同 EXE）。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#分工规则"},
    {"q": ["AI 训练负责人负责什么", "AI 负责人的任务有哪些"], "a": "负责 8 项：云端 GPU 训练环境、数据集格式约定、模型②波形识别、模型①本地 agent 模型、GPU 强化学习、模型量化流水线、云端推理 API、分布式 agent（云端侧）。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#三、你的任务清单"},
    {"q": ["项目做到什么进度了", "完成到什么程度"], "a": "截至第 26 轮全量测试 100% 通过：系统底座、10 个桌面应用、桌面美化交互、FPGA GPU 图形加速（设计侧完成，只差 bitstream）。",
     "s": "AI训练交接包(1)/04_项目背景/项目总览.md#当前状态一览"},
    {"q": ["为什么要用 Zynq 而不是普通单片机", "Zynq 的优势是什么"], "a": "Zynq-7020 集成了 ARM（PS）和 FPGA（PL），可以在 PL 里做硬件加速（自研 GPU、CNN 加速器、示波器采集核心），这是普通单片机做不到的。",
     "s": "AI训练交接包(1)/04_项目背景/项目总览.md#一、项目目标"},
    {"q": ["屏幕参数是什么", "用什么屏幕"], "a": "7 寸 1024×600 RGB LCD + GT911 电容触摸，另有 HDMI 输出。",
     "s": "AI训练交接包(1)/04_项目背景/项目总览.md#阶段 0：系统底座"},
    {"q": ["音频编解码芯片是什么", "音频用什么芯片"], "a": "ES8388 音频编解码器，功放是 MD8002A。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"q": ["项目里有哪些 AI 模型", "要训练哪些模型"], "a": "两个模型：模型②示波器波形识别（训练+量化）、模型①本地 agent 用的小语言模型（LoRA 微调+量化）；另外还有 GPU 强化学习（示波器自动设置、音频 EQ 调优）。",
     "s": "AI训练交接包(1)/00_README_先读我.md#一、你负责什么（一句话）"},
]

# 下面把 FACT_BANK 拆成多个 list 便于阅读与增量维护；最终合并。
_FACTS_HARDWARE: List[Dict] = [
    # ================= 二、Zynq-7020 硬件规格 =================
    {"q": ["板子有多少内存", "内存多大"], "a": "1 GB DDR3，这是部署本地模型时的硬约束。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"q": ["DDR3 的型号和参数", "DDR 是什么颗粒"], "a": "Micron MT41K256M16 RE-125（4Gb/颗），16 位位宽，2 颗并联成 32 位总线（约 1 GB），DDR3_1066F，533.333 MHz。",
     "s": "work/prev_cnn/设计文档/BOARD_CONFIG.md#DDR3"},
    {"q": ["ARM CPU 主频多少", "处理器跑多快"], "a": "ARM 时钟（APU）666.666666 MHz，双核 Cortex-A9。",
     "s": "work/prev_cnn/设计文档/BOARD_CONFIG.md#1. PS（processing_system7）关键配置"},
    {"q": ["PS 的晶振频率", "PS_CLK 是多少"], "a": "PS_CLK 晶振 33.333333 MHz。",
     "s": "work/prev_cnn/设计文档/BOARD_CONFIG.md#1. PS（processing_system7）关键配置"},
    {"q": ["自研 GPU 的寄存器地址", "GPU 在哪个地址"], "a": "自研 GPU（gpu_0）在 0x43CB0000，窗口 64K。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表（唯一权威）"},
    {"q": ["示波器的寄存器地址", "示波器在哪个地址"], "a": "示波器（scope_0）在 0x43CC0000。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表（唯一权威）"},
    {"q": ["CNN 加速器的地址", "CNN 预留地址是什么"], "a": "CNN 预留两个地址：conv_pool 在 0x43CD0000，fc 在 0x43CE0000（0x43CD0000 往后全空，新地址从这里拿）。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表（唯一权威）"},
    {"q": ["lcd 的地址是什么", "显示相关外设地址"], "a": "lcd_pl_pwm 在 0x43C00000，lcd_vtc 在 0x43C10000，lcd v_frmbuf_rd 在 0x43C20000。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表（唯一权威）"},
    {"q": ["音频相关外设地址", "i2s 和 audio 地址"], "a": "audio_formatter 在 0x43C50000，i2s_receiver 在 0x43C60000，i2s_transmitter 在 0x43C70000。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表（唯一权威）"},
    {"q": ["i2c 总线地址", "i2c2 在哪个地址"], "a": "i2c2 在 0x41600000（ES8388 音频等挂在 i2c 上）。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表（唯一权威）"},
    {"q": ["当前 FPGA 资源占用多少", "资源够不够用"], "a": "截至 2026-09-30：Slice LUTs 33.55%、Slice Registers 27.06%、BRAM 11.07%、DSP48E1 只有 1.82%（余量巨大）、Bonded IOB 73.60%（注意快满）、XADC 0%（空闲）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#当前 FPGA 资源占用"},
    {"q": ["PL 的系统时钟引脚", "sys_clk 在哪个引脚"], "a": "sys_clk（PL 时钟）在 U18（50MHz），sys_rst_n 复位在 N16（低有效）。",
     "s": "work/prev_cnn/设计文档/BOARD_CONFIG.md#3. 外设引脚"},
    {"q": ["串口参数是什么", "UART 怎么配置"], "a": "UART0 控制台在 MIO14/15，波特率 115200，8N1，无流控。",
     "s": "work/prev_cnn/设计文档/BOARD_CONFIG.md#启动 / I/O"},
    {"q": ["启动设备是什么", "从什么启动"], "a": "QSPI Flash 在 MIO1..6，SD0 在 MIO40..45（CD=MIO10），支持 SD 卡启动（boot mode=SD）。",
     "s": "work/prev_cnn/设计文档/BOARD_CONFIG.md#启动 / I/O"},
    {"q": ["板子的 IP 会不会变", "为什么连不上板子"], "a": "板子是 DHCP，重启后 IP 可能变（历史有 192.168.10.23 / .18 / .13 / 192.168.43.210），连不上就先问一声别盲扫。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#板子的地址（会变！）"},
]

_FACTS_SSH: List[Dict] = [
    # ================= 三、SSH / 刷 bitstream / 原子写入 =================
    {"q": ["怎么 SSH 连板子", "板子登录命令"], "a": "ssh zynq@192.168.10.23，密码 123456；sudo -n 免密可用。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#SSH"},
    {"q": ["刷 bitstream 的正确姿势", "怎么安全刷写 bitstream"], "a": "用原子写入：写 .new → 校验 md5 → mv → 重启。千万别直接覆盖 /mnt/boot/system.bit，否则 WiFi 断了会写坏启动分区。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#红线 5：刷 bitstream 前打招呼"},
    {"q": ["原子烧录用的什么脚本", "flash 脚本是哪个"], "a": "复用 flash_scope.py 的原子烧录逻辑（写 .new → 校验 md5 → mv → 重启）。",
     "s": "AI训练交接包(1)/04_项目背景/★技术实施计划_v2_20260930.md#2.1 ✅ 已可用，直接复用"},
    {"q": ["bitstream 放在板子哪里", "system.bit 路径"], "a": "/mnt/boot/system.bit，备份在 /mnt/boot/system.bit.bak_*。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#八、板子上的重要文件"},
    {"q": ["刷 bitstream 前要注意什么", "刷写前要做什么"], "a": "先在群里说“我要刷 bitstream，板子会重启一分钟”，因为板子只有一个，刷写会重启，影响别人实验。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#红线 5：刷 bitstream 前打招呼"},
    {"q": ["板子时区设置", "时区是哪个"], "a": "已设为 Asia/Shanghai（北京时间），重启后保持。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#SSH"},
    {"q": ["怎么重启桌面服务", "重启桌面命令"], "a": "sudo systemctl restart zynq-desktop；桌面日志在 /var/log/zynq-desktop.log。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#系统服务"},
    {"q": ["怎么注入触摸事件做自动化测试", "UI 自动化怎么点"], "a": "通过文件注入：echo 400,300 | sudo tee /tmp/ui_tap 是单击，echo drag:100,100;200,200 是拖拽。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#★ 触摸注入（自动化测试用）"},
    {"q": ["怎么给板子截图", "截图命令"], "a": "sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot.raw，输出 BGR24 原始数据，分辨率 1024×600。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#截图"},
    {"q": ["怎么远程执行板子命令", "PC 怎么控制板子"], "a": "电脑上用 board.py：python D:\\ubuntu_iso\\board.py 命令 远程执行，-p 本地 远程 传文件，shot.py 截图。",
     "s": "AI训练交接包(1)/04_项目背景/项目总览.md#四、快速使用"},
    {"q": ["内核备份在哪", "zImage 备份路径"], "a": "/mnt/boot/zImage.bak_*。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#八、板子上的重要文件"},
]

_FACTS_ES8388: List[Dict] = [
    # ================= 四、ES8388 音频寄存器 =================
    {"q": ["ES8388 的 DAC 音量寄存器", "怎么调 DAC 音量"], "a": "0x1A/0x1B 是 DAC 音量 L/R，0x00 = 0 dB（最大）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["ES8388 芯片控制寄存器", "0x00 和 0x01 是什么"], "a": "0x00 是芯片控制 1（正常值 0x06），0x01 是芯片控制 2（正常值 0x50）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["ES8388 Vpp_scale 寄存器", "怎么提高输出摆幅"], "a": "0x1D 是 DAC Control 8，Vpp_scale 位：1 = 4.0V，默认 0 = 3.5V。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["ES8388 输出使能寄存器", "怎么让 DAC 输出到功放"], "a": "0x27/0x2A 是混合器 L/R，写 0xF8 表示 DAC→输出使能。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["耳机座音量寄存器", "Output 1 音量怎么调"], "a": "0x2E/0x2F 是 Output 1 音量（→LOUT1/ROUT1，耳机座），最大 33。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["喇叭音量寄存器", "Output 2 音量怎么调"], "a": "0x30/0x31 是 Output 2 音量（→LOUT2/ROUT2，功放/喇叭），最大 33。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["ES8388 ADC 电源寄存器", "录音时 0x03 该写多少"], "a": "0x03 是 ADC 电源：驱动设 0x09，但已知能录音的值是 0x51。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["ES8388 ADC 输入选择", "麦克风输入寄存器"], "a": "0x0A 是 ADC 输入选择：驱动设 0x50（LINE），麦克风应该是 0x00。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["ES8388 ADC 控制 5", "0x0D 寄存器"], "a": "0x0D 是 ADC 控制 5：驱动设 0x03，已知能录音的值是 0x02。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"q": ["怎么读 ES8388 寄存器", "i2cget 命令"], "a": "sudo i2cget -f -y 1 0x10 0x1d（-f 绕过驱动占用），写用 i2cset。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#常用命令"},
    {"q": ["怎么用命令行调音量", "amixer 命令"], "a": "amixer -c 0 -q sset 'Output 1' 33 调耳机座音量，Output 2 调喇叭。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#常用命令"},
    {"q": ["怎么在板子上录音", "arecord 命令"], "a": "arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 3 /tmp/rec.wav（硬件只接受 S24_LE，采集在 device 1）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#常用命令"},
    {"q": ["喇叭放音的根因是什么", "音频之前为什么有问题"], "a": "喇叭放音根因已修复：BCLK 从 TX 改到 RX，消除了跨时钟域。",
     "s": "AI训练交接包(1)/01_任务书/01_功能清单.md#二、音频链路"},
    {"q": ["录音现在有什么问题", "麦克风录音质量"], "a": "麦克风能录到数据但质量有问题：右声道反复 255/0、电平偏低（约 -44 dBFS），可能有 S24_LE 对齐问题。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#1. 采集通路修复"},
    {"q": ["音频服务在哪个端口", "audio 服务怎么调"], "a": "音频服务 zynq-audio 在 HTTP :8767，可 curl /state 或 POST /play 放音。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#系统服务"},
    {"q": ["放音支持的格式", "音频要什么采样率"], "a": "硬件只接受 44100 Hz / 2ch（放音侧），其他格式由音频服务自动转换。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#三、音频硬件（ES8388）"},
]

_FACTS_SCOPE: List[Dict] = [
    # ================= 五、示波器 IP 寄存器与接口 =================
    {"q": ["示波器 IP 叫什么", "示波器 IP 名字"], "a": "dsh:user:scope_cap_axi:1.0，基址 0x43CC0000（窗口 64K）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"q": ["示波器采集深度多少", "一次采多少点"], "a": "4096 点 × 8 bit，双 bank；基础采样率 100 MHz / DIV（默认 DIV=5 → 20 MSPS）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"q": ["示波器时基范围", "DEC 是什么"], "a": "抽取 DEC 1~255，对应 50 ns/点 ~ 12.7 µs/点。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"q": ["示波器触发方式", "触发支持什么"], "a": "触发 = 电平 + 边沿（升/降）+ 模式（Auto/Normal/Single）+ 预触发。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"q": ["示波器 CTRL 寄存器", "0x00 寄存器是什么"], "a": "偏移 0x00 是 CTRL：W[0]=start W[1]=stop，R[0]=done R[1]=busy R[2]=triggered R[3]=rd_bank。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["示波器源选择寄存器", "SRC 寄存器"], "a": "偏移 0x04 是 SRC：[0]=源（0 DDS / 1 ADC），[2:1]=波形。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["DDS 频率怎么算", "FREQ 寄存器"], "a": "偏移 0x10 是 FREQ（DDS 频率字）：f = FREQ × 20MHz / 2³²。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["示波器触发电平寄存器", "TRIGLEV"], "a": "偏移 0x14 是 TRIGLEV，触发电平 0~255；0x18 是 TRIGCFG（[0]=边沿，[2:1]=模式）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["示波器预触发点数", "PRE 寄存器默认多少"], "a": "偏移 0x1C 是 PRE，预触发点数默认 2048。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["怎么读示波器采样数据", "RDATA 寄存器"], "a": "偏移 0x28 是 RDATA，读一次返回 4 个样本；0x20 是 START 读起点，0x24 是 RDPTR 读指针。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["怎么确认示波器 IP 在线", "VERSION 寄存器"], "a": "偏移 0x34 是 VERSION，值为 0x53434F50（“SCOP”），用来确认 IP 在线。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"q": ["示波器读取接口函数名", "capture_once 怎么用"], "a": "capture_once(src, dec, trig_level, trig_edge, trig_mode, timeout_ms) 返回 dict，含 samples（4096 个 8 位样本）、fs_hz、trig_pos、meta；失败返回 {ok: False, error: ...} 不抛异常。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ③：示波器读取接口"},
    {"q": ["怎么设置 DDS 参数", "set_dds 接口"], "a": "set_dds(waveform, freq_hz, amp=255)：waveform 0=正弦 1=方波 2=三角 3=锯齿，返回 {ok: True} 或 {ok: False, error: ...}。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ③：示波器读取接口"},
    {"q": ["示波器 V2 接外部信号用什么方案", "怎么接真实信号"], "a": "推荐片内 XADC（底板 J1/CON1 已引出，零飞线），12 位 / 1 MSPS / 输入 0~1V；备选 DVP 口 + 野火 EBF410196（8位/20MSPS，需飞 9 根线）。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#1. 示波器 V2 —— 接真实外部信号"},
]

_FACTS_CNN: List[Dict] = [
    # ================= 六、CNN 加速器量化方案 =================
    {"q": ["CNN 加速器用的量化公式", "requantization 公式是什么"], "a": "out = relu/sat((acc × MFQ) >> 16)，即累加结果乘 MFQ 后算术右移 16 位，再 ReLU/饱和。",
     "s": "AI训练交接包(1)/00_README_先读我.md#★ 量化必须沿用上一轮的方案"},
    {"q": ["MFQ 默认值是多少", "MFQ=119 是什么意思"], "a": "MFQ=119 是上一轮 MNIST 模型在主机侧校准出来的值，不是硬件常量；MFQ 在 HLS 里是 s_axilite 寄存器，每次调用都能传不同值。",
     "s": "ai_training/docs/00_接口冻结单.md#4.2 依据（请主线融合负责人核对一遍）"},
    {"q": ["MFQ 是常量还是寄存器", "MFQ 能改吗"], "a": "MFQ 是 s_axilite 寄存器，不是烧进 bitstream 的常量，每次调用都可以传不同值，所以本项目采用逐层 MFQ（conv1/conv2/fc 各一个）。",
     "s": "ai_training/docs/00_接口冻结单.md#4.1 结论先说"},
    {"q": ["CNN 网络结构是什么", "LeNet 结构细节"], "a": "输入 28×28×1 → Conv1(3×3, 1→8)+ReLU+2×2Pool → 13×13×8 → Conv2(3×3, 8→16)+ReLU+2×2Pool → 5×5×16=400 → FC(400→N)。",
     "s": "ai_training/docs/00_接口冻结单.md#1. ★★ 最关键的一条：输入几何锁定 28×28"},
    {"q": ["为什么输入锁定 28×28", "32×32 为什么不行"], "a": "按 HLS 公式 OH=(IH-KH+1)/P：28×28 展平后 FC 输入正好是 16×5×5=400；而 32×32 会得到 576，与 fc in=400 矛盾，改尺寸等于改加速器。",
     "s": "ai_training/docs/00_接口冻结单.md#1. ★★ 最关键的一条：输入几何锁定 28×28"},
    {"q": ["CNN 权重内存布局", "权重怎么排布"], "a": "卷积权重 w[(oc*IN_CH+ic)*KH*KW + ky*KW + kx]，全连接权重 w[oc*IN + i]；不传偏置（bias=False 训练）。",
     "s": "ai_training/src/common/qmodel.py#硬件事实"},
    {"q": ["CNN 的累加是什么位宽", "acc 用什么类型"], "a": "acc = Σ img×w 是 int8×int8 累加，用 ap_int<32> 存储。",
     "s": "ai_training/src/common/qmodel.py#硬件事实"},
    {"q": ["量化溢出约束", "MFQ 不能太大"], "a": "acc×MFQ 在 ap_int<32> 里做，溢出会回绕，约束是 max|acc| × MFQ < 2^31。",
     "s": "ai_training/docs/00_接口冻结单.md#4.4 溢出"},
    {"q": ["MFQ 该怎么标定", "MFQ 值怎么算"], "a": "让 int8 输出用满 [0,127] 而不饱和：需要的 MFQ ≈ 127 × 65536 / max|acc|；不同层累加次数差 40 倍以上，所以用逐层 MFQ。",
     "s": "ai_training/docs/00_接口冻结单.md#4.3 为什么新模型不能直接用 119"},
    {"q": ["非真实 requantization 是什么坑", ">>8 有什么问题"], "a": "上一轮 M4b-4 用粗略 >>8 代替真实 requantization，导致 argmax 落在错误类别；必须用真实 requantization（MFQ 校准）。",
     "s": "AI训练交接包(1)/00_README_先读我.md#五、上一轮的经验"},
    {"q": ["CNN 输入量化怎么定义", "int8 输入怎么来的"], "a": "输入量化唯一定义：int8 = uint8 - 128，即 i8 = clip(u8 - 128, -128, 127)，scale=1.0 不做缩放。",
     "s": "ai_training/docs/00_接口冻结单.md#3. ★ 输入量化"},
    {"q": ["波形识别分几类", "类别有哪些"], "a": "9 类（顺序冻结）：sine 正弦、square 方波、triangle 三角、sawtooth 锯齿、noise 噪声、glitch 毛刺、clipping 削顶、signal_loss 丢信号、duty_abnormal 占空比异常。",
     "s": "ai_training/docs/00_接口冻结单.md#★ 类别表（冻结，禁止改顺序）"},
    {"q": ["CNN 上板怎么验证", "[CNN OK] 是什么意思"], "a": "喂同样输入、看输出是否逐点一致：上一轮验证输出 [CNN OK] 676/676、400/400、10/10 点一致；这依赖 reference_out.bin 做基准。",
     "s": "AI训练交接包(1)/00_README_先读我.md#四、你最重要的一件事：接口"},
    {"q": ["CNN 有没有偏置", "为什么要 bias=False"], "a": "硬件不传偏置数组，所以网络必须 bias=False 训练（或主机侧把偏置折进别处）。",
     "s": "ai_training/src/common/qmodel.py#硬件事实"},
    {"q": ["cache 一致性是什么坑", "CNN 结果尾部全 0"], "a": "输出缓冲最后一条不完整 cache line 未失效会导致板端结果尾部全 0；裸机用 Xil_DCacheFlushRange/Xil_DCacheInvalidateRange，Linux 用户态用 mmap + msync/O_SYNC。",
     "s": "AI训练交接包(1)/00_README_先读我.md#五、上一轮的经验"},
]

_FACTS_IFACE: List[Dict] = [
    # ================= 七、接口约定单四个接口 =================
    {"q": ["接口①是什么", "模型交付格式"], "a": "接口①是模型交付格式：quantized_model/ 含 weights.bin（int8 权重，说明 DDR 内存布局）、model_spec.json、reference_in.bin、reference_out.bin、README.md。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ①：模型交付格式"},
    {"q": ["reference_out.bin 为什么必须", "为什么要有参考输出"], "a": "板子侧集成时唯一可靠的验证方式是“喂同样输入看输出是否逐点一致”，没有 reference_out.bin 就无法判断硬件输出对不对。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#为什么必须要 reference_in.bin + reference_out.bin"},
    {"q": ["接口②是什么", "数据集格式"], "a": "接口②是数据集格式：dataset/ 含 meta.json + train/val/test，每个样本是 NNNNN.npy + NNNNN.json，label 与 dds_params 可追溯（DDS 参数即标签）。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ②：数据集格式"},
    {"q": ["接口③是什么", "示波器读取接口"], "a": "接口③是示波器读取接口：capture_once（读一次采集）和 set_dds（设 DDS 参数），函数名和返回 key 不许改，失败不抛异常要有超时。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ③：示波器读取接口"},
    {"q": ["接口④是什么", "云端推理 API"], "a": "接口④是云端推理 API：POST http://<云端>/infer，body 含 type（waveform|chat）、data、hint、api_key，返回 ok/label/confidence/detail/elapsed_ms。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ④：云端推理 API"},
    {"q": ["接口⑤是什么", "硬件操作接口"], "a": "接口⑤是硬件操作接口（主线融合→云协同 EXE）：GET /tools、POST /tool、POST /chat，硬件工具含 _reg_read/_reg_write/_hdl_edit/_vivado_build/_flash_bitstream 等。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ⑤：硬件操作接口"},
    {"q": ["为什么输入形态用 STFT 不用折线图", "STFT 的理由"], "a": "STFT 同样复用 2D CNN 加速器（IP 不改）但信息保留远好于栅格化折线图，对频率类故障（谐波/拍频/漂移）更敏感。",
     "s": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#★ 关于输入形态：用 STFT，不用折线图"},
    {"q": ["分级推理怎么降级", "离线模式怎么触发"], "a": "板子优先用本地量化小模型；置信度 < 0.7 或类型不支持送云端；云端不可达/超时（建议 2.5s）降级到本地并提示“离线模式”；联网后自动恢复。",
     "s": "ai_training/docs/00_接口冻结单.md#6. 接口 ④：云端推理 API + 分级推理降级约定"},
    {"q": ["STFT 的参数是什么", "时频图怎么算"], "a": "4096 个 8 位样本 → 28×28 uint8 时频图：中心化、NFFT=512、HOP=132（28 帧）、Hann 窗、对数频率轴 28 行取最大值、dB 后相对峰值 60dB 动态范围截断。",
     "s": "ai_training/docs/00_接口冻结单.md#2. ★ 输入形态：STFT 的精确定义"},
    {"q": ["数据集增强有哪些", "怎么数据增强"], "a": "训练时在线做：频率轴循环平移 ±4 行、时间轴平移 ±3 列、增益+亮度缩放、加性噪声 σ∈[0,6]；不做水平翻转（锯齿翻转会变另一种波形）。",
     "s": "ai_training/docs/00_接口冻结单.md#数据增强（训练时在线做，不进数据集文件）"},
]

_FACTS_RULE: List[Dict] = [
    # ================= 八、协作红线 =================
    {"q": ["协作红线有哪些", "六条红线是什么"], "a": "红线1 BD 修改权归主线融合；红线2 地址分配主线统一管；红线3 bitstream 主线统一出；红线4 接口定了不许单方面改；红线5 刷 bitstream 前打招呼；红线6 模型交付必须带 reference_out.bin。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#④ 协作红线"},
    {"q": ["为什么要红线 1", "BD 为什么不能乱改"], "a": "BD（block design）是三个人唯一的共享资源，并发改必然冲突（后写的覆盖前面的），所以要改得提需求给主线融合负责人统一改。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#红线 1"},
    {"q": ["多 agent 并发规则", "多个 agent 怎么协作"], "a": "多个 agent 并行的收益来自任务独立而不是同时改同一个东西；BD 同时只允许一个 agent 改、板子同时只允许一个 agent 操作、Vivado 编译排队、按文件域划分。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#三、多 agent 并发规则"},
    {"q": ["文件域怎么划分", "谁负责哪些文件"], "a": "DSH agent 管 agent/tools.py 与融合；Codex 管 RTL 与工具链脚本；示波器负责人 agent 管 10_自研示波器/；AI 负责人 agent 管训练脚本、模型文件、云端代码。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#文件域划分建议"},
    {"q": ["出流后要测什么", "回归清单是什么"], "a": "回归清单：桌面能起、音频能放能录、示波器能采、GPU 能跑、CNN 能跑（若集成）、agent 能起；任何一项不过就不能当作可交付版本。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#六、回归清单"},
    {"q": ["冲突了怎么办", "两人改了同一文件"], "a": "原则：谁的改动更接近主工程以谁为准；同一文件后改的人负责合并，BD 被并发改就从最近备份恢复重做，板子状态不对就重启跑回归清单。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#八、如果冲突了怎么办"},
]

_FACTS_PITFALL: List[Dict] = [
    # ================= 九、已知的坑 =================
    {"q": ["XADC 输入有什么危险", "XADC 超压会怎样"], "a": "XADC 输入超 1V 会打坏芯片，必须先做分压/保护电路再接信号。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["HLS 打包有什么坑", "core_revision bug"], "a": "HLS 打包 IP 时 core_revision 被设成 YYMMDDHHMM 格式的当前时间，2026 年得到 26xxxxxxxx 超过 int32 上限报 bad lexical cast；用 ipx::package_project 绕过。",
     "s": "AI训练交接包(1)/04_项目背景/项目总览.md#⏳ 唯一剩余：生成 bitstream"},
    {"q": ["Verilog 不写位宽有什么坑", "wire 默认位宽"], "a": "wire dec1 = ... 不写位宽就是 1 位线，会把 8 位值截断。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["BRAM 推断失败是什么坑", "存储器铺成触发器"], "a": "存储器写端口放在带复位的 always 块里会导致 BRAM 推断失败，8192×8 被铺成 65536 个触发器。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["读端口寄存输出的坑", "预取地址要注意什么"], "a": "读端口是寄存输出时，预取地址要提前一拍，否则读到的是上一拍的数据。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["done 信号的坑", "done 写成单拍脉冲"], "a": "done 写成单拍脉冲时，软件轮询抓不到，应保持电平直到被清除。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["帧缓冲双缓冲的坑", "截图为什么是旧画面"], "a": "帧缓冲是 1024×1200 双缓冲只有 600 行可见，直接读开头会读到过期画面，要用 FBIOGET_VSCREENINFO 查 yoffset。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#截图"},
    {"q": ["路径含中文的坑", "HLS 为什么报 illegal character"], "a": "Xilinx 工具在 Windows 上不认中文/非 ASCII 路径，可构建工程必须放纯 ASCII 路径（如 D:\\FPGA2026_PRJ）。",
     "s": "work/prev_cnn/交接文档/02_阶段经验与踩坑合集.md#A. 关键环境坑"},
    {"q": ["NUM_MI 的坑", "单从机 AXI 为什么卡死"], "a": "自定义 IP 作唯一从机（NUM_MI=1）时真机 AXI 写卡死，用 NUM_MI=2（多放一个 AXI GPIO）与已验证跑通的结构一致。",
     "s": "work/prev_cnn/交接文档/02_阶段经验与踩坑合集.md#B. Block Design / 综合坑"},
    {"q": ["位宽截断的坑", "3'd8 为什么变 0"], "a": "3'd8（3 位）超出位宽会被截断成 0，常量位宽要够，用 4'd8、7'h40。",
     "s": "work/prev_cnn/交接文档/02_阶段经验与踩坑合集.md#B. Block Design / 综合坑"},
    {"q": ["systemd 配置的坑", "heredoc 写服务"], "a": "heredoc 写 systemd 配置要用 <<'EOF'（不展开），否则 $(...) 会被提前求值；systemd 的 PATH 没有 /usr/sbin，i2cget 要写绝对路径。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["服务权限的坑", "User= 权限受限"], "a": "服务用 User= 时权限受限，需要 root 的命令要加 + 前缀（如 ExecStartPre=+...）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"q": ["工具链版本有什么坑", "Vivado 版本混用"], "a": "上一轮是 2018.3，主工程是 2026.1，HLS C++ 可能有 API 差异；2018.3 打不开 2026.1 的工程。",
     "s": "AI训练交接包(1)/00_README_先读我.md#五、上一轮的经验"},
    {"q": ["刷 bitstream 直接覆盖的后果", "为什么不能直接 cp"], "a": "直接覆盖 /mnt/boot/system.bit，WiFi 断了会写坏启动分区，必须用原子写入（写 .new → 校验 md5 → mv → 重启）。",
     "s": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#红线 5：刷 bitstream 前打招呼"},
]

_FACTS_OTHER: List[Dict] = [
    # ================= 十、其它（STFT/RL/agent 工具/分级推理） =================
    {"q": ["示波器自动设置为什么用 RL", "RL 适合什么"], "a": "调参数是序列决策问题（调一次看效果再调），RL 比监督学习更合适；且回报可算、稠密、采样快（一次采集 4.3ms）、演示肉眼可见。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 E：强化学习训练"},
    {"q": ["示波器自动设置的回报函数", "RL 回报怎么定义"], "a": "回报 = w1·(波形占屏比例 60~80%) + w2·(触发电平居中度) + w3·(显示 2~5 周期) - w4·(丢触发惩罚)。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#4b. 示波器自动设置"},
    {"q": ["RL 训练哪两个策略网络", "RL 的目标"], "a": "两个：① 示波器自动设置（动作=触发电平/时基/垂直增益）；② 音频 EQ 调优（动作=EQ 参数，回报=频响平坦度）。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 E：强化学习训练"},
    {"q": ["agent 硬件工具集有哪些", "硬件工具有哪些"], "a": "_reg_read/_reg_write（寄存器）、_hdl_edit（改 RTL/BD）、_vivado_build（综合实现出流）、_flash_bitstream（刷写）、_acoustic_measure（声学自测）、_scope_capture（示波器读取）。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#3. Agent 硬件工具集"},
    {"q": ["变更单机制是什么", "变更单记什么"], "a": "每次硬件改动自动记录：变更内容/依据/预期效果/验证结果/回滚命令，挂进 _policy_gate，存 JSON + Markdown 双份。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#4. 变更单机制"},
    {"q": ["自动回滚怎么做", "没改善怎么恢复"], "a": "判定无改善时自动恢复到改前状态：复用 flash_scope.py 原子写入，寄存器类改动记原值写回，回滚后再验证一次确认恢复。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#6. 自动回滚"},
    {"q": ["分布式 agent 怎么同步", "板子和 PC 记录同步"], "a": "记录以 PC 端为主（空间大 UI 强），板子只存最近 N 条；增量同步 + 时间戳，冲突以 PC 为准；板子离线时 PC 端仍可用。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#8. 分布式 agent（云端侧）"},
    {"q": ["波形识别模型验收标准", "准确率要求多少"], "a": "测试集准确率 > 95%，导出格式符合约定，板子侧能加载。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 C：模型 ②"},
    {"q": ["云端推理 API 延迟要求", "API 多快"], "a": "验收要求延迟 < 3 s。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 G：云端推理 API"},
    {"q": ["声学自测闭环是什么", "怎么自测频响"], "a": "放扫频 → 麦克风录回 → 算传递函数 H(f)=Y(f)/X(f) → 1/3 倍频程平滑 → 画频响曲线；验证峰值位置正确、能测出小喇叭低频塌陷。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#2. 声学自测闭环"},
    {"q": ["数据标签为什么 100% 精确", "标签怎么来的"], "a": "用示波器 DDS 参数化扫描自动生成数据，DDS 参数即标签，可无限重放、零人工成本，解决了 AI 项目最大死穴（没有标注数据）。",
     "s": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#2. 数据集自产"},
    {"q": ["本地 agent 模型用什么基座", "小模型选什么"], "a": "基座选小参数模型（Qwen 系列 0.5B~1.5B），LoRA 微调（领域数据 = FPGA/音频/项目知识），再 INT8/INT4 量化。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 D：模型 ①"},
    {"q": ["板子 1GB 能跑本地 LLM 吗", "0.5B INT4 多少内存"], "a": "0.5B 模型 INT4 约 350 MB，板子只有 1 GB RAM，紧张但可能可行；不行就纯走云端，板子只做转发。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 D：模型 ①"},
    {"q": ["本地 agent 模型的诚实提醒", "LoRA 一定比 RAG 好吗"], "a": "竞赛项目几百~几千条对话微调出的模型，效果大概率不如“大模型 + RAG”；要效果最好走 RAG，要“自研模型”说法走 LoRA。",
     "s": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 D：模型 ①"},
    {"q": ["AI 负责人要交付哪些接口", "要交付什么格式"], "a": "三个接口：接口①模型交付格式、接口②数据集格式（与示波器方共同）、接口④云端推理 API。",
     "s": "AI训练交接包(1)/00_README_先读我.md#四、你最重要的一件事：接口"},
    {"q": ["agent 现有的工具集", "现在有哪些工具"], "a": "shell / read / write / edit / glob / grep / http / todo / system / speak / listen / audio，架构用 REGISTRY + @tool 装饰器 + _policy_gate 安全门。",
     "s": "AI训练交接包(1)/01_任务书/01_功能清单.md#五、Agent"},
    {"q": ["agent HTTP API 有哪些端点", "agent 接口"], "a": "GET /tools、POST /tool、POST /chat（在 8080 端口）。",
     "s": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#Agent API"},
]

FACT_BANK += (_FACTS_HARDWARE + _FACTS_SSH + _FACTS_ES8388 + _FACTS_SCOPE +
              _FACTS_CNN + _FACTS_IFACE + _FACTS_RULE + _FACTS_PITFALL + _FACTS_OTHER)

# ---------------------------------------------------------------------------
# ★ 拒答样本 REFUSAL_BANK —— 文档里没有答案的问题，教模型说“不知道”
# ---------------------------------------------------------------------------
REFUSAL_QUESTIONS = [
    "今天天气怎么样", "明天会不会下雨", "帮我查一下上海今天的温度", "今天星期几",
    "现在几点钟", "今天股市涨了还是跌了", "推荐一只股票", "比特币现在多少钱",
    "怎么做红烧肉", "西红柿炒鸡蛋怎么做", "哪家外卖好吃", "附近有什么好吃的餐厅",
    "最近有什么好看的电影", "推荐一部电视剧", "哪个明星结婚了", "世界杯冠军是谁",
    "昨天足球比赛谁赢了", "NBA 谁得分最高", "圆周率第 100 位是多少", "1+1 等于几",
    "帮我写一首诗", "讲个笑话", "给我唱首歌", "明天我该穿什么衣服",
    "怎么减肥", "怎么美白", "失眠怎么办", "头疼吃什么药", "感冒了怎么办",
    "房价会涨还是跌", "我该买哪套房子", "怎么考清华", "高考作文怎么写",
    "帮我算命", "我的星座运势怎么样", "双色球开奖号码", "彩票买什么号",
    "特朗普说了什么", "美国大选谁赢了", "俄乌战争进展", "人民币汇率多少",
    "帮我翻译一段英文", "python 怎么学", "java 和 go 哪个好", "怎么装 windows",
    "游戏怎么通关", "我的世界怎么玩", "王者荣耀哪个英雄强", "原神怎么抽卡",
    "今天吃什么", "晚饭吃什么", "中午吃什么好", "奶茶哪个牌子好喝",
    "我的手机坏了怎么办", "怎么修电脑", "空调不制冷怎么办", "洗衣机怎么用",
    "给我讲讲相对论", "黑洞是什么", "宇宙有多大", "人类起源是什么",
    "我该选什么专业", "毕业了找什么工作", "怎么谈恋爱", "怎么追女生",
]

# 拒答答案模板（都包含拒答 marker，供 eval 判定与模型学习）
REFUSAL_ANSWERS = [
    "这个问题不在我的知识范围内，我无法回答。",
    "抱歉，这个问题超出了我的知识范围，我不知道答案。",
    "我无法回答这个问题，因为它与项目资料无关。",
    "这个问题不在我的知识范围内，建议你咨询其他途径。",
    "我不知道这个问题的答案。",
    "抱歉，这个问题我回答不了。",
]

# ---------------------------------------------------------------------------
# 问法扩充模板（对同一事实生成多条指令；语义不变，属数据增强）
# ---------------------------------------------------------------------------
_WRAPPERS = [
    "{q}",                    # 原问法
    "请问，{q}",             # 加礼貌前缀
    "我想了解一下，{q}",     # 加求知前缀
]

# 后缀替换：把问句末尾的“吗？/呢？/？”归一，配合 wrapper 避免双问号
def _norm_q(q: str) -> str:
    q = q.strip()
    if q.endswith("？"):
        q = q[:-1]
    return q


def _expand_questions(qs: List[str]) -> List[str]:
    """把一个事实的若干问法用模板扩成更多条（去重、保序）。"""
    out: List[str] = []
    for q in qs:
        base = _norm_q(q)
        for w in _WRAPPERS:
            v = w.format(q=base)
            # 统一补上问号
            if not v.endswith("？") and not v.endswith("?"):
                v += "？"
            if v not in out:
                out.append(v)
    return out


# ---------------------------------------------------------------------------
# 文档发现 / markdown 切块
# ---------------------------------------------------------------------------
def default_project_root() -> str:
    """从本文件位置向上找项目根目录（包含 ai_training 的目录）。"""
    d = os.path.abspath(_HERE)
    for _ in range(5):
        if os.path.isdir(os.path.join(d, "ai_training")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.abspath(os.path.join(_HERE, "..", "..", ".."))


def iter_md_blocks(text: str, fallback_title: str) -> List[Tuple[List[str], str]]:
    """把 markdown 按标题层级拆成 (title_path, body) 块。"""
    blocks: List[Tuple[List[str], str]] = []
    stack: List[Tuple[int, str]] = []
    cur: List[str] = []

    def flush():
        if cur:
            body = "\n".join(cur).strip()
            if body:
                title = [t for _, t in stack] or [fallback_title]
                blocks.append((title, body))
        cur.clear()

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip().strip("#").strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            cur.append(line)
    flush()
    return blocks


def _hard_split(para: str, hi: int) -> List[str]:
    """把超长段落按句末标点/换行切开。"""
    parts = re.split(r"(?<=[。；！？!?;])\s*|\n", para)
    out: List[str] = []
    cur = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        while len(p) > hi:
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:hi])
            p = p[hi:]
        if cur and len(cur) + len(p) + 1 <= hi:
            cur = cur + " " + p
        elif not cur:
            cur = p
        else:
            out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def split_into_chunks(text: str, lo: int = 300, hi: int = 600) -> List[str]:
    """把一段文本切成 300~600 字的 chunks（按空行/句子边界，尽量保持完整）。"""
    units: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= hi:
            units.append(para)
        else:
            units.extend(_hard_split(para, hi))
    chunks: List[str] = []
    buf = ""
    for u in units:
        if not buf:
            buf = u
        elif len(buf) + len(u) + 1 <= hi:
            buf += "\n" + u
        else:
            chunks.append(buf)
            buf = u
    if buf:
        chunks.append(buf)
    # 去掉过短、几乎无信息的块（只含分隔线/标题符号）
    out = [c for c in chunks if len(c.strip()) >= 20]
    return out


def extract_py_docstring(path: str) -> str:
    """只提取 .py 文件的模块级 docstring（作为语料来源之一）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return ""
    m = re.match(r'^\s*(?:\xef\xbb\xbf)?(?:"{3}|\'\'\')', text)
    if not m:
        return ""
    quote = text[m.start():m.start() + 3]
    end = text.find(quote, m.end())
    if end < 0:
        return ""
    return text[m.end():end].strip()


def discover_docs(project_root: str) -> List[Tuple[str, str]]:
    """返回 [(source_relpath, text), ...]，其中 .py 只取 docstring。"""
    docs: List[Tuple[str, str]] = []
    for rel, exts in DOC_ROOTS:
        base = os.path.join(project_root, rel)
        if not os.path.isdir(base):
            print(f"  [跳过] 目录不存在：{base}")
            continue
        for dirpath, _dirs, files in os.walk(base):
            # 跳过产物目录
            if any(skip in dirpath for skip in ("__pycache__", ".git", "node_modules", ".cache")):
                continue
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                if ext not in exts:
                    continue
                fp = os.path.join(dirpath, fn)
                if ext == ".py":
                    text = extract_py_docstring(fp)
                    if not text:
                        continue
                else:
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            text = f.read()
                    except (OSError, UnicodeDecodeError):
                        continue
                if not text.strip():
                    continue
                relpath = os.path.relpath(fp, project_root).replace(os.sep, "/")
                docs.append((relpath, text))
    return docs


def build_chunks(project_root: str) -> List[Dict]:
    """发现文档 → 按标题切块 → 输出 chunk 列表。"""
    chunks: List[Dict] = []
    n = 0
    for relpath, text in discover_docs(project_root):
        fallback = relpath
        for title_path, body in iter_md_blocks(text, fallback):
            for piece in split_into_chunks(body):
                chunks.append({
                    "id": f"chunk-{n:05d}",
                    "source": relpath,
                    "title_path": title_path,
                    "text": piece,
                })
                n += 1
    return chunks


# ---------------------------------------------------------------------------
# LoRA 指令数据集（sharegpt 风格）
# ---------------------------------------------------------------------------
def build_lora_entries() -> List[Dict]:
    """由 FACT_BANK + REFUSAL 生成 sharegpt 风格样本，每条带 source。"""
    entries: List[Dict] = []
    for fact in FACT_BANK:
        for q in _expand_questions(fact["q"]):
            entries.append({
                "conversations": [
                    {"from": "human", "value": q},
                    {"from": "gpt", "value": fact["a"]},
                ],
                "source": fact["s"],
                "topic": "grounded",
            })
    for i, q in enumerate(REFUSAL_QUESTIONS):
        a = REFUSAL_ANSWERS[i % len(REFUSAL_ANSWERS)]
        entries.append({
            "conversations": [
                {"from": "human", "value": q},
                {"from": "gpt", "value": a},
            ],
            "source": "out_of_scope",   # 拒答样本本身无对应文档
            "topic": "refusal",
        })
    return entries


def split_train_val(entries: List[Dict], val_ratio: float = 0.1,
                    seed: int = 20261001) -> Tuple[List[Dict], List[Dict]]:
    """按固定种子分层切出验证集（拒答样本也按比例分层保留）。"""
    rng = random.Random(seed)
    grounded = [e for e in entries if e["topic"] == "grounded"]
    refusal = [e for e in entries if e["topic"] == "refusal"]
    rng.shuffle(grounded)
    rng.shuffle(refusal)
    n_gv = max(1, int(len(grounded) * val_ratio))
    n_rv = max(1, int(len(refusal) * val_ratio))
    val = grounded[:n_gv] + refusal[:n_rv]
    train = grounded[n_gv:] + refusal[n_rv:]
    # 训练集里也保留若干拒答样本，保证模型学到“拒答”
    return train, val


def write_jsonl(path: str, entries: List[Dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # newline="\n"：强制 LF 换行（远端 Linux 要求，避免 Windows 写出 CRLF）
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 RAG 知识库 + LoRA 指令数据集")
    ap.add_argument("--project-root", default=None, help="项目根目录（含 ai_training 的目录）")
    ap.add_argument("--out-kb", default=DEFAULT_KB, help="知识库输出目录")
    ap.add_argument("--out-lora", default=DEFAULT_LORA, help="LoRA 数据输出目录")
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=20261001)
    args = ap.parse_args()

    root = args.project_root or default_project_root()
    print(f"项目根目录：{root}")

    print("\n[1/3] 构建 RAG 知识库（chunks）...")
    chunks = build_chunks(root)
    kb_path = os.path.join(args.out_kb, "chunks.jsonl")
    os.makedirs(args.out_kb, exist_ok=True)
    write_jsonl(kb_path, chunks)
    print(f"  产出 {len(chunks)} 个 chunks → {kb_path}")
    if chunks:
        avg = sum(len(c["text"]) for c in chunks) / len(chunks)
        print(f"  平均 chunk 长度：{avg:.0f} 字")

    print("\n[2/3] 生成 LoRA 指令数据集...")
    entries = build_lora_entries()
    train, val = split_train_val(entries, args.val_ratio, args.seed)
    train_path = os.path.join(args.out_lora, "train.jsonl")
    val_path = os.path.join(args.out_lora, "val.jsonl")
    write_jsonl(train_path, train)
    write_jsonl(val_path, val)
    n_grounded = sum(1 for e in entries if e["topic"] == "grounded")
    n_refusal = sum(1 for e in entries if e["topic"] == "refusal")
    print(f"  总样本 {len(entries)} 条（grounded={n_grounded}, refusal={n_refusal}）")
    print(f"  train={len(train)} 条 → {train_path}")
    print(f"  val={len(val)} 条 → {val_path}")

    print("\n[3/3] 输出摘要")
    print(f"  kb/chunks.jsonl : {len(chunks)} chunks")
    print(f"  lora_data/train.jsonl : {len(train)}")
    print(f"  lora_data/val.jsonl : {len(val)}")
    print("BUILD_CORPUS_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
