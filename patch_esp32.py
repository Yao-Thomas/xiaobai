#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ESP32 那份 main.cpp 改成「问板子上的 Agent」，生成 patch 后的文件。

**只读原文件、只写新文件**，原工程一个字节都不动。
输出：17_板载Agent/esp32_改造/main.cpp
"""
import os
import re
import sys

SRC = r"D:\ubuntu_iso\agent\esp32\src\main.cpp"      # 当初 robocopy 的只读副本
DST_DIR = (r"D:\总文件夹\FPGA2026_项目交接包\17_板载Agent\esp32_改造")
DST = os.path.join(DST_DIR, "main.cpp")

BOARD_IP = "192.168.10.18"
BOARD_PORT = 8765

src = open(SRC, encoding="utf-8", errors="replace").read()
orig = src

changes = []

# ---- 1) WiFi: 原来连手机热点 "001"，改成和板子同一个网 ----
if '#define WIFI_SSID        "001"' in src:
    src = src.replace('#define WIFI_SSID        "001"',
                      '#define WIFI_SSID        "CMCC-Y2Ss"   // ← 和 Zynq 板同一个网')
    changes.append("WIFI_SSID 001 -> CMCC-Y2Ss")
if '#define WIFI_PASSWORD    "yaoenqi127"' in src:
    src = src.replace('#define WIFI_PASSWORD    "yaoenqi127"',
                      '#define WIFI_PASSWORD    "e513wifi"')
    changes.append("WIFI_PASSWORD -> e513wifi")

# ---- 2) 加一个板子地址宏 ----
anchor = '#define DEEPSEEK_KEY "YOUR_DEEPSEEK_API_KEY_HERE"'
if anchor in src:
    src = src.replace(anchor, anchor + '\n'
        '// ★ 大脑搬到 Zynq 板上了：语音识别出来的文字 POST 给板载 Agent，\n'
        '//   由它调 DeepSeek（key 在板子上，不再落在固件里）\n'
        '#define BOARD_AGENT      "http://%s:%d"' % (BOARD_IP, BOARD_PORT))
    changes.append("新增 BOARD_AGENT 宏")

# ---- 3) 把直连 DeepSeek 换成问板子 ----
old_url = 'http.begin("https://api.deepseek.com/chat/completions");'
new_url = 'http.begin(String(BOARD_AGENT) + "/intent");   // ★ 改成问板载 Agent'
if old_url in src:
    src = src.replace(old_url, new_url)
    changes.append("URL -> 板载 Agent /intent")

old_hdr = '    http.addHeader("Authorization", "Bearer " + String(DEEPSEEK_KEY));\n'
if old_hdr in src:
    src = src.replace(old_hdr, "")          # 板子那边有 key，设备上不需要
    changes.append("去掉 Authorization 头（key 不再下发到设备）")

old_body = '''    String body = "{\\"model\\":\\"deepseek-chat\\",\\"messages\\":["
                  "{\\"role\\":\\"system\\",\\"content\\":\\"" + sys + "\\"},"
                  "{\\"role\\":\\"user\\",\\"content\\":\\"" + user_text + "\\"}"
                  "],\\"max_tokens\\":200,\\"temperature\\":0.1}";'''
new_body = '''    // ★ 板载 Agent 的 /intent 接口：前端自带 system 提示词、关掉工具，
    //   板子只负责调模型；回复是 OpenAI 形状，下面解析 "content" 的代码不用改。
    String body = "{\\"stateless\\":true,\\"tools\\":false,"
                  "\\"system\\":\\"" + sys + "\\","
                  "\\"text\\":\\"" + user_text + "\\"}";'''
if old_body in src:
    src = src.replace(old_body, new_body)
    changes.append("请求体 -> {stateless, tools, system, text}")
else:
    print("!! 没找到原始 body，需要人工改（下面会给出上下文）")

old_log = 'Serial.printf("[DS] HTTP=%d\\n", code);'
if old_log in src:
    src = src.replace(old_log,
                      'Serial.printf("[DS] HTTP=%d\\n", code);   // 200 = 板子答的')

os.makedirs(DST_DIR, exist_ok=True)
open(DST, "w", encoding="utf-8", newline="\n").write(src)

print("原始: %s (%d 字节)" % (SRC, len(orig)))
print("输出: %s (%d 字节)" % (DST, len(src)))
print("改动 %d 处:" % len(changes))
for c in changes:
    print("   -", c)
if src == orig:
    sys.exit("!! 没有任何改动，请检查锚点")
