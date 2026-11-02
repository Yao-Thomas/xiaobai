#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_to_board.py —— PC 侧一键部署（板子上电后跑这个）

做三件事：
  ① 等板子回来（持续 ping/SSH，最多等 N 分钟）
  ② 把所有文件传上去（含今天的修复和新增）
  ③ 在板子上跑 deploy_all.sh

用法:
    python deploy_to_board.py                # 等 10 分钟，然后部署
    python deploy_to_board.py --wait 30      # 等 30 分钟
    python deploy_to_board.py --now          # 不等，直接试
"""
import argparse
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# 要传的文件： (本地路径, 板子路径)
FILES = [
    # ---- 温度保护 ----
    ("thermal_guard.py",            "/home/zynq/thermal_guard.py"),
    ("cool_down.py",                "/home/zynq/cool_down.py"),
    ("thermal-guard.service",       "/tmp/thermal-guard.service"),
    ("thermal-cooldown.service",    "/tmp/thermal-cooldown.service"),
    ("deploy_all.sh",               "/tmp/deploy_all.sh"),
    # ---- 声学自测 ----
    ("acoustic_selftest.py",        "/home/zynq/acoustic_selftest.py"),
    ("analyze_wav.py",              "/home/zynq/analyze_wav.py"),
    ("audio_spectrum.py",           "/home/zynq/audio_spectrum.py"),
    # ★ 采集修复：ES8388 的 0x0A 要设成 0x00（麦克风），否则采集近乎静音
    ("audio_cap_init.py",           "/home/zynq/audio_cap_init.py"),
    # ---- 波形 AI 链路（A7 的软件部分）----
    ("waveform_ai.py",              "/home/zynq/waveform_ai.py"),
    ("verify_dataset.py",           "/home/zynq/verify_dataset.py"),
    # ★★★ 波形模型上板（AI 训练负责人交付 v1.0，2026-10-02）★★★
    #   weights.bin     4480 B  int8 权重，128 字节对齐布局
    #   reference_*.bin 上板验收用的输入/期望输出（64 组）
    #   verify_wave_onboard.py  验收脚本（板子上 sudo 跑）
    ("wave_model/weights.bin",         "/home/zynq/wave_weights.bin"),
    ("wave_model/reference_in.bin",    "/home/zynq/wave_reference_in.bin"),
    ("wave_model/reference_out.bin",   "/home/zynq/wave_reference_out.bin"),
    ("wave_model/model_spec.json",     "/home/zynq/wave_model_spec.json"),
    ("verify_wave_onboard.py",         "/home/zynq/verify_wave_onboard.py"),
    # ★ 真机端到端验收（测试集在 PC 上用 gen_wave_e2e_set.py 生成）
    ("verify_wave_e2e_board.py",       "/home/zynq/verify_wave_e2e_board.py"),
    ("gen_wave_e2e_set.py",            "/home/zynq/gen_wave_e2e_set.py"),
    # ★ 开机预留区相关的工具
    ("patch_dtb_mem.py",               "/home/zynq/patch_dtb_mem.py"),
    ("deploy_dtb_mem.sh",              "/home/zynq/deploy_dtb_mem.sh"),
    ("bit2bin.py",                     "/home/zynq/bit2bin.py"),
    ("load_cnn_now.sh",                "/home/zynq/load_cnn_now.sh"),
    # ★ 调试脚本（留着，下次出问题直接跑）
    ("dbg_reserved.py",                "/home/zynq/dbg_reserved.py"),
    ("dbg_probe3.py",                  "/home/zynq/dbg_probe3.py"),
    ("dbg_layer_cmp.py",               "/home/zynq/dbg_layer_cmp.py"),
    ("dbg_stability.py",               "/home/zynq/dbg_stability.py"),
    ("dbg_cache.py",                   "/home/zynq/dbg_cache.py"),
    ("dbg_wave_step.py",               "/home/zynq/dbg_wave_step.py"),
    ("dbg_wave_iso.py",                "/home/zynq/dbg_wave_iso.py"),
    # ★ 接口 ③：示波器读取接口（capture_once / set_dds）——
    #   波形 AI 链和 hw_scope_capture 都靠它
    ("scope_capture.py",            "/home/zynq/scope_capture.py"),
    # ---- 硬件工具集 / 变更管理 ----
    ("agent/hw_tools.py",           "/home/zynq/agent/hw_tools.py"),
    ("agent/hw_change.py",          "/home/zynq/agent/hw_change.py"),
    ("agent/core.py",               "/home/zynq/agent/core.py"),
    # ★ 分级推理：断网也能用（规则层 + 本地模型接口 + 云端）
    ("agent/tiers.py",              "/home/zynq/agent/tiers.py"),
    # ★ 对话管理：会话持久化 + 上下文裁剪 + 多会话
    ("agent/sessions.py",           "/home/zynq/agent/sessions.py"),
    # ---- ★ "agent 改 FPGA"闭环 ----
    ("fpga_build_daemon.py",        "/home/zynq/fpga_build_daemon.py"),
    # ---- ★ 云协同统一入口 ----
    ("cloud_api.py",                "/home/zynq/cloud_api.py"),
    ("cloud-api.service",           "/home/zynq/cloud-api.service"),
    ("install_cloud_api.sh",        "/home/zynq/install_cloud_api.sh"),
    # ---- ★ 桌面：变更历史 App（「agent 改硬件」的可视化证据）----
    #   传到 ui/ 下。apps_hwchange.py 是【新应用】，桌面每次打开应用都会
    #   importlib.reload，所以传上去就能用，不用重启桌面。
    #   desktop.py 改了 APPS 表（加了"变更历史"这一项），★ 需要重启桌面才生效。
    ("ui_fix/apps_hwchange.py",     "/home/zynq/ui/apps_hwchange.py"),
    ("ui_fix/desktop.py",           "/tmp/desktop.py.new"),
    # ---- 离线测试 ----
    ("test_hw_tools.py",            "/home/zynq/test_hw_tools.py"),
    ("test_hw_change.py",           "/home/zynq/test_hw_change.py"),
    ("test_selftest_math.py",       "/home/zynq/test_selftest_math.py"),
    ("test_fpga_loop.py",           "/home/zynq/test_fpga_loop.py"),
    ("test_cloud_api_http.py",      "/home/zynq/test_cloud_api_http.py"),
    ("test_hwchange_ui.py",         "/home/zynq/test_hwchange_ui.py"),
    # ---- 工具：shell 脚本体检（PC 上没 bash 时用）----
    ("shell_lint.py",               "/home/zynq/shell_lint.py"),
    ("dbg_rollback.py",             "/home/zynq/dbg_rollback.py"),
    # ---- ★ CNN 驱动（波形模型就靠它）----
    #   2026-10-02 起支持逐层 MFQ（conv1/conv2/fc 各传各的），
    #   并且多了 wave_classify() / verify_wave_reference()。
    ("cnn_linux.py",                "/home/zynq/cnn_linux.py"),
    ("repack_handover.py",          "/home/zynq/repack_handover.py"),
    # ---- 新增的测试 ----
    ("test_webui_api.py",           "/home/zynq/test_webui_api.py"),
    ("test_llm_key.py",             "/home/zynq/test_llm_key.py"),
    ("test_wave_integration.py",    "/home/zynq/test_wave_integration.py"),
    # ★ 本地 RAG（AI 负责人交付，接进 tiers.py 的 Tier 1）
    ("test_rag_offline.py",         "/home/zynq/test_rag_offline.py"),
    # ★ 板子实时状态进知识库（我们独有的能力）
    ("live_kb.py",                  "/home/zynq/live_kb.py"),
    # ★ 客户端（聊天界面 + 语音）
    ("apps_agent.py",               "/home/zynq/ui/apps_agent.py"),
    ("render_board_app.py",         "/home/zynq/render_board_app.py"),
    ("xb_chat.py",                  "/home/zynq/xb_chat.py"),
    ("xb_audio.py",                 "/home/zynq/xb_audio.py"),
    ("shot_chat.py",                "/home/zynq/shot_chat.py"),
    ("probe_mic.py",                "/home/zynq/probe_mic.py"),
    ("test_voice_loop.py",          "/home/zynq/test_voice_loop.py"),
    # ★ AI 负责人另两个 RL 策略的板端驱动
    ("policy_mlp.py",               "/home/zynq/policy_mlp.py"),
    ("scope_policy.py",             "/home/zynq/scope_policy.py"),
    ("infer_local.py",              "/home/zynq/infer_local.py"),
    ("verify_dds_loop.py",          "/home/zynq/verify_dds_loop.py"),
    # ★ 云协同诊断
    ("check_cloud_from_pc.py",      "/home/zynq/check_cloud_from_pc.py"),
    ("test_xb_client.py",           "/home/zynq/test_xb_client.py"),
    # ★ 三个交付物的权重和参数
    ("scope_policy_deliv/weights.bin",         "/home/zynq/scope_policy/weights.bin"),
    ("scope_policy_deliv/model_spec.json",     "/home/zynq/scope_policy/model_spec.json"),
    ("scope_policy_deliv/reference_in.bin",    "/home/zynq/scope_policy/reference_in.bin"),
    ("scope_policy_deliv/reference_out.bin",   "/home/zynq/scope_policy/reference_out.bin"),
    ("eq_policy_deliv/weights.bin",            "/home/zynq/eq_policy/weights.bin"),
    ("eq_policy_deliv/model_spec.json",        "/home/zynq/eq_policy/model_spec.json"),
    ("eq_policy_deliv/reference_in.bin",       "/home/zynq/eq_policy/reference_in.bin"),
    ("eq_policy_deliv/reference_out.bin",      "/home/zynq/eq_policy/reference_out.bin"),
    ("rag_kb/chunks.jsonl",         "/home/zynq/agent/kb/chunks.jsonl"),
    ("ai_delivery/03_源码/agent/rag.py", "/home/zynq/agent/rag.py"),
    # ---- 音频修复（24 位转换）----
    ("ui_fix/audio_alsa_svc.py",    "/tmp/audio_alsa_svc.py"),
]

# ★ 注意：audio_alsa_svc.py 的替换要在停服务后做，脚本里单独处理


def run(cmd, timeout=180):
    p = subprocess.run(cmd, shell=isinstance(cmd, str),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, cwd=HERE)
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


def board_alive():
    rc, out = run([sys.executable, "board.py", "hostname -I"], timeout=60)
    return rc == 0 and "192.168" in out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=10,
                    help="最多等多少分钟（默认 10）")
    ap.add_argument("--now", action="store_true", help="不等，直接试")
    a = ap.parse_args()

    print("=" * 74)
    print(" 一键部署到板子")
    print("=" * 74)

    # ---------- ① 等板子 ----------
    if not a.now:
        deadline = time.time() + a.wait * 60
        print("\n【1】等板子回来（最多 %.0f 分钟）" % a.wait)
        n = 0
        while time.time() < deadline:
            n += 1
            if board_alive():
                print("   ✓ 第 %d 次检查：板子在！(%.0f 秒)"
                      % (n, a.wait * 60 - (deadline - time.time())))
                break
            print("   [%s] 第 %d 次：还没回来" %
                  (time.strftime("%H:%M:%S"), n))
            time.sleep(20)
        else:
            print("\n ★ 等了 %.0f 分钟还没等到板子。" % a.wait)
            print("   上电后再跑一次： python deploy_to_board.py")
            return 1
    else:
        print("\n【1】--now：直接试")
        if not board_alive():
            print("   ★ 板子连不上。先上电。")
            return 1
        print("   ✓ 板子在")

    # ---------- ② 传文件 ----------
    print("\n【2】传文件")
    failed = []
    for src, dst in FILES:
        lp = os.path.join(HERE, src)
        if not os.path.exists(lp):
            print("   - %-28s 本地没有，跳过" % src)
            continue
        rc, out = run([sys.executable, "board.py", "-p", lp, dst], timeout=180)
        if rc == 0:
            print("   ✓ %-28s -> %s" % (src, dst))
        else:
            print("   ✗ %-28s 失败: %s" % (src, out.strip()[:100]))
            failed.append(src)

    if failed:
        print("\n ★ 有 %d 个文件没传成功：%s" % (len(failed), ", ".join(failed)))
        print("   注意：hw_tools.py / hw_change.py 必须传成功，否则硬件工具用不了")

    # ---------- ③ 音频修复（单独，要停服务）----------
    print("\n【3】应用音频 24 位转换修复")
    fix = """cd /home/zynq/ui
if [ -f /tmp/audio_alsa_svc.py ]; then
  TS=$(date +%Y%m%d_%H%M%S)
  sudo systemctl stop zynq-audio 2>/dev/null
  [ -f audio_alsa_svc.py ] && cp audio_alsa_svc.py audio_alsa_svc.py.bak_deploy_$TS
  sudo cp /tmp/audio_alsa_svc.py audio_alsa_svc.py
  sudo chown zynq:zynq audio_alsa_svc.py
  sudo systemctl start zynq-audio
  sleep 4
  echo "  zynq-audio: $(systemctl is-active zynq-audio)"
  echo "  md5: $(md5sum audio_alsa_svc.py | cut -d' ' -f1)"
else
  echo "  (没传 audio_alsa_svc.py)"
fi
"""
    with open(os.path.join(HERE, "_apply_audio.sh"), "w", encoding="utf-8",
              newline="\n") as f:
        # ★ newline="\n" 是必须的：Windows 上默认会把 \n 写成 \r\n，
        #   传到 Linux 上 sh 就会报
        #       cd: $'/home/zynq/ui\r': No such file or directory
        #       syntax error: unexpected end of file
        #   （踩过一次：部署时音频修复那一步整个失败了）
        f.write(fix)
    rc, out = run([sys.executable, "board.py", "-f", "_apply_audio.sh"], timeout=180)
    print(out.strip()[-500:])

    # ---------- ④ 跑部署 ----------
    print("\n【4】在板子上跑 deploy_all.sh")
    rc, out = run([sys.executable, "board.py",
                   "-f", "run_deploy_all.sh"], timeout=900)
    # run_deploy_all.sh 可能还没生成，退而用 sudo sh
    if rc != 0 or "deploy_all" not in out:
        rc, out = run([sys.executable, "board.py",
                       "sudo sh /tmp/deploy_all.sh"], timeout=900)
    print(out.strip()[-4000:])

    print()
    print("=" * 74)
    print(" 部署结束")
    print("=" * 74)
    print(" 下一步建议：")
    print("   ① ★ 云协同服务（新增）:")
    print("      python board.py \"sudo sh /home/zynq/install_cloud_api.sh\"")
    print("      -> 装好会打印 token 和客户端要连的地址")
    print("   ② 声学自测（要出声）:")
    print("      python board.py \"sudo python3 /home/zynq/acoustic_selftest.py\"")
    print("   ③ 看温度:")
    print("      python board.py \"sudo python3 /home/zynq/thermal_guard.py --status\"")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
