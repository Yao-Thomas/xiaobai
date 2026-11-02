# -*- coding: utf-8 -*-
"""build_code_pkg.py —— 组装「小白智枢」完整代码包并打成 RAR

用法：
    python build_code_pkg.py            # 从板子拉最新代码 + 组装 + 打包
    python build_code_pkg.py --no-board # 只用本地已有文件（板子离线时）

产物：
    D:\\总文件夹\\FPGA2026\\小白智枢_完整代码包_<日期>.rar
"""
import os
import shutil
import subprocess
import sys
import time

TODAY = time.strftime("%Y%m%d")
PKG_ROOT = r"D:\总文件夹\FPGA2026\_code_pkg"
PKG = os.path.join(PKG_ROOT, "小白智枢_完整代码包_" + TODAY)
RAR_EXE = r"C:\Program Files\WinRAR\Rar.exe"
OUT_RAR = r"D:\总文件夹\FPGA2026\小白智枢_完整代码包_%s.rar" % TODAY

BOARD_PY = r"D:\ubuntu_iso"

# ---------- 板端要拉的文件清单（用通配符，避免漏） ----------
BOARD_FILES = [
    # 桌面与 UI
    "ui/desktop.py", "ui/fbui.py", "ui/screen_guard.py",
    "ui/scope_dual.c", "ui/scope_processing.py", "ui/scope_capture_dataset.py",
    # 示波器（双通道 + 模板识别引擎）
    "ui/apps_scope_dual.py", "ui/apps_scope.py", "ui/apps_scope_hub.py",
    "ui/apps_wave_ai.py",
    # ★ 识别引擎核心（git 里没有！）
    "ui/wave_templates.py",
    # 小白（Agent UI）
    "ui/apps_agent.py",
    # 音频
    "ui/audio_alsa_svc.py", "ui/audio_pl.py", "ui/audio_cap_init.py",
    # 其他应用（体现 25 个应用）
    "ui/apps_browser.py", "ui/apps_music.py", "ui/apps_notes.py",
    "ui/apps_settings.py", "ui/apps_sys.py", "ui/apps_files.py",
    "ui/apps_wifi.py", "ui/apps_clock.py", "ui/apps_calc.py",
    "ui/apps_draw.py", "ui/apps_mines.py", "ui/apps_fight.py",
    "ui/apps_mc.py", "ui/apps_gpu.py", "ui/apps_novel.py",
    "ui/apps_filehelper.py", "ui/apps_term.py", "ui/apps_view.py",
    "ui/apps_about.py", "ui/apps_chime.py", "ui/apps_change.py",
    "ui/apps_wall.py",
    # 云 API / 后端
    "cloud_api.py", "thermal_guard.py", "infer_local.py",
    "wave_model_spec.json", "wave_weights.bin",
    # Agent 服务
    "agent/main.py", "agent/core.py", "agent/tools.py", "agent/hw_tools.py",
    "agent/llm.py", "agent/tts.py", "agent/asr.py", "agent/voice_loop.py",
    "agent/audio_client.py", "agent/config.py", "agent/guard.py",
    "agent/policy.py", "agent/rag.py", "agent/sessions.py",
    "agent/shared_chat.py", "agent/tiers.py", "agent/spill.py",
    "agent/hw_change.py",
    # 工具脚本
    "es8388_rw.py", "dump_es8388_regs.py", "audio_verify.py",
]

# ---------- 板端配置/数据（用 sudo 读的） ----------
BOARD_ROOT_FILES = [
    "/home/zynq/.scope_templates.json",
    "/etc/xiaobai-cloud.json",
    "/etc/systemd/system/zynq-desktop.service",
    "/etc/systemd/system/zynq-agent.service",
    "/etc/systemd/system/zynq-audio.service",
    "/etc/systemd/system/zynq-audio.service.d/output2-off.conf",
]

# ---------- PC 端 ----------
PC_FILES = [
    "xb_chat.py", "scope_panel.py", "xb_client.py", "xb_pcsr.py",
    "xb_audio.py", "系统管家小白_scope.spec",
    "系统管家小白.spec", "系统管家小白_wave_ai.spec",
    "build_code_pkg.py", "sync_board.py", "board.py",
]


def log(msg):
    print("  " + msg)


def ensure_dirs():
    for d in ("01_板端代码/board_ui", "01_板端代码/board_agent",
              "01_板端代码/board_root", "01_板端代码/systemd",
              "01_板端代码/data", "02_PC端代码", "03_AI训练与量化",
              "04_PL工程", "05_文档"):
        os.makedirs(os.path.join(PKG, d), exist_ok=True)


def pull_board():
    sys.path.insert(0, BOARD_PY)
    os.environ.setdefault("BOARD_IP", "192.168.43.210")
    import board as B
    try:
        B.conn()
    except Exception as e:
        log("❌ 连不上板子: %s" % e)
        return False

    ok, miss = 0, []
    for rel in BOARD_FILES:
        remote = "/home/zynq/" + rel
        if rel.startswith("ui/"):
            local = os.path.join(PKG, "01_板端代码/board_ui", os.path.basename(rel))
        elif rel.startswith("agent/"):
            local = os.path.join(PKG, "01_板端代码/board_agent", os.path.basename(rel))
        else:
            local = os.path.join(PKG, "01_板端代码/board_root", os.path.basename(rel))
        try:
            B.get(remote, local)
            ok += 1
        except Exception:
            miss.append(rel)
    log("板端代码: 成功 %d / 缺失 %d" % (ok, len(miss)))
    if miss:
        log("  缺失: " + ", ".join(miss[:12]))

    # 二进制/配置
    for rem in BOARD_ROOT_FILES:
        base = os.path.basename(rem)
        if rem.startswith("/etc/systemd"):
            local = os.path.join(PKG, "01_板端代码/systemd", base)
        else:
            local = os.path.join(PKG, "01_板端代码/data", base)
        try:
            if rem.startswith("/etc"):
                o = B.run("sudo cat '%s' > /tmp/_pk_cfg 2>/dev/null; "
                          "sudo chown zynq:zynq /tmp/_pk_cfg; echo ok" % rem,
                          timeout=60, quiet=True)
                B.get("/tmp/_pk_cfg", local)
            else:
                B.get(rem, local)
        except Exception as e:
            log("  配置拉取失败 %s: %s" % (rem, e))

    # libscopedual.so（需要编译产物）
    try:
        B.get("/home/zynq/ui/libscopedual.so",
              os.path.join(PKG, "01_板端代码/board_ui", "libscopedual.so"))
        log("  已拉 libscopedual.so")
    except Exception:
        pass
    return True


def copy_pc():
    n = 0
    for f in PC_FILES:
        p = os.path.join(BOARD_PY, f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(PKG, "02_PC端代码", f))
            n += 1
    log("PC 端代码: %d 个" % n)


def copy_ai():
    n = 0
    # 训练脚本 + 量化权重
    for src, dst in [
        (r"D:\wavetrain\quantized_v3", "03_AI训练与量化/quantized_v3"),
        (r"D:\ubuntu_iso\ai_src\wave_ai", "03_AI训练与量化/wave_ai_源码"),
    ]:
        if os.path.isdir(src):
            # 排除 __pycache__ / .pyc
            shutil.copytree(src, os.path.join(PKG, dst),
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(
                                '__pycache__', '*.pyc', '*.pyo'))
            n += 1
    # 交付包里的模型与异常库
    deliv = os.path.join(PKG, "03_AI训练与量化/模型交付")
    os.makedirs(deliv, exist_ok=True)
    for f in ("model_bundle.pt", "anomaly_stats.npz"):
        p = os.path.join(r"D:\ubuntu_iso\ai_deliv", f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(deliv, f))
            n += 1
    log("AI 相关: %d 项" % n)


def copy_pl():
    """只挑关键 PL 产物：bitstream / tcl 打包脚本 / xsa，最多 30 个，单个 < 40MB。"""
    src = r"D:\总文件夹\FPGA2026"
    n = 0
    picked = []
    exts = (".bit", ".xsa", ".hwh")
    for root, dirs, files in os.walk(src):
        # 跳过明显的巨型/无关目录
        dirs[:] = [d for d in dirs
                   if d not in (".Xil", "软件安装包", "系统备份", "__pycache__")]
        for f in files:
            low = f.lower()
            full = os.path.join(root, f)
            try:
                sz = os.path.getsize(full)
            except Exception:
                continue
            if sz > 40 * 1024 * 1024:
                continue
            if low.endswith(exts):
                picked.append((0, full, f, sz))          # 最高优先
            elif low.endswith(".tcl") and ("build" in low or "audio" in low
                                           or "bd_" in low or "fix" in low):
                picked.append((1, full, f, sz))
    picked.sort()
    for _, full, f, sz in picked[:30]:
        try:
            shutil.copy2(full, os.path.join(PKG, "04_PL工程", f))
            n += 1
        except Exception:
            pass
    log("PL 工程/比特流: %d 个（候选 %d）" % (n, len(picked)))


def copy_docs():
    n = 0
    for f in ("交接文档/04_构建与复现指南.md", "交接文档/完工版_项目全景_20261026.md",
              "交接文档/03_板卡配置.md", "海报_系统框图_绘制说明.md"):
        p = os.path.join(r"D:\总文件夹\FPGA2026", f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(PKG, "05_文档", os.path.basename(p)))
            n += 1
    log("文档: %d 个" % n)


README = """# 小白智枢 —— 完整代码包

> 基于 AMD Xilinx ZYNQ-7020 的边缘 AI 智能示波器
> 生成时间：{today}

## 目录结构

```
01_板端代码/
   board_ui/      板端桌面与全部应用（4 页 25 应用）
                  ★ wave_templates.py = 12 类波形识别引擎（核心）
                  ★ apps_scope_dual.py = 双通道示波器 + AI 分析卡片
                  ★ apps_agent.py = 系统管家小白（键盘/语音/手写）
                  ★ audio_alsa_svc.py / audio_pl.py = ES8388 音频服务
                  ★ scope_dual.c = 波形绘制与包络折线的 C 加速库
   board_agent/   Agent 服务（DeepSeek 后端、工具层、TTS/ASR）
   board_root/    云 API、温度守护、本地 CNN 推理、模型规格
   systemd/       各个服务的 unit 与 drop-in
   data/          .scope_templates.json（模板库）、wave_weights.bin（4.5 KB INT8 权重）
02_PC端代码/     PC 客户端（聊天 + 云协同示波器）与 PyInstaller spec
03_AI训练与量化/  训练脚本、量化权重、云端多模态模型（model_bundle.pt）
04_PL工程/       Vivado tcl / bit / 硬件描述
05_文档/         构建复现指南、项目全景、板卡配置
```

## 硬件平台
- 板卡：正点原子 领航者 ZYNQ7020 V3.9（xc7z020clg400-2）
- 系统：Ubuntu 20.04 armv7l，kernel 5.4.0-xilinx-v2020.2
- 显示：LCD 1024×600，双缓冲 framebuffer
- 音频：ES8388 + MD8002A，双路输出（Output1 耳机 / Output2 板载喇叭）

## 关键实现要点
1. **PL 侧 11 个自研 IP**：双通道采集(20 MS/s, 4096 深, 10 bit)、CNN 卷积、
   CNN 全连接、GPU 波形渲染、I2S 音频、VTC 视频时序、PWM 背光等。
2. **INT8 CNN 硬件加速**：9 类，权重 4.5 KB，单次推理 20~25 ms，无需联网。
3. **12 类波形模板在线学习**：谐波签名(6 维) + 包络特征(64 维)，
   现场摆一种新波形，10 秒内学会并稳定识别；不用重训模型、不用重烧 FPGA。
4. **云边协同分层**：本地识别为主结论，云端多模态(16 类) + 大模型仅作参考补充。
5. **语音链路**：百度 TTS（离线兜底 espeak-ng）→ 8757 音频服务 → ES8388。

## 复现步骤（概要）
1. 板端烧写 PL bitstream，启动 Linux。
2. 把 `01_板端代码/` 下文件按目录放回 `/home/zynq/ui`、`/home/zynq/agent`。
3. `systemd/` 里的 unit 放 `/etc/systemd/system/`，`systemctl daemon-reload`。
4. `data/` 里模板库与权重放回 `/home/zynq/`。
5. PC 端启动云端多模态服务（8000）与客户端 exe。

详细步骤见 `05_文档/04_构建与复现指南.md`。

## 说明
- `wave_templates.py` 的模板库（`.scope_templates.json`）是实测数据，
  新环境首次运行会自动加载；不同信号源下可重新现场学习。
- 板载喇叭与耳机口是 ES8388 两路独立输出；默认关闭 Output2（板载喇叭），
  恢复方法：`export BOARD_SPK=on`。
"""


def write_readme():
    with open(os.path.join(PKG, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.format(today=TODAY))
    log("README.md")


def pack():
    if not os.path.isfile(RAR_EXE):
        log("❌ 找不到 Rar.exe")
        return
    # 用 rar a -r -ep1（保留一层目录）
    # rar a 是增量更新：不先删会把上次的旧条目（如已排除的 pycache）留在包里
    if os.path.isfile(OUT_RAR):
        try:
            os.remove(OUT_RAR)
        except Exception as e:
            log("⚠ 旧包删不掉（是否被占用？）: %s" % e)
    cmd = [RAR_EXE, "a", "-r", "-m3", "-ep1", "-y", OUT_RAR, PKG]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk",
                       errors="replace")
    if r.returncode in (0, 1):
        sz = os.path.getsize(OUT_RAR) / 1e6
        log("✅ 已打包: %s (%.1f MB)" % (OUT_RAR, sz))
    else:
        log("❌ rar 失败 rc=%d" % r.returncode)
        log((r.stdout or "")[-400:])
        log((r.stderr or "")[-400:])


def main():
    use_board = "--no-board" not in sys.argv
    if os.path.isdir(PKG):
        shutil.rmtree(PKG, ignore_errors=True)
    ensure_dirs()

    if use_board:
        pull_board()
    else:
        log("跳过板端拉取（--no-board）")
    copy_pc()
    copy_ai()
    copy_pl()
    copy_docs()
    write_readme()

    total = sum(len(fs) for _, _, fs in os.walk(PKG))
    sz = sum(os.path.getsize(os.path.join(r, f))
             for r, _, fs in os.walk(PKG) for f in fs) / 1e6
    log("暂存目录: %s  (%d 文件, %.1f MB)" % (PKG, total, sz))
    pack()


if __name__ == "__main__":
    main()
