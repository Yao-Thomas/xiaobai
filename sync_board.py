#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_board.py —— 把板端关键文件同步到 PC，纳入 Git 版本控制

用法：
    $env:BOARD_IP = "192.168.10.20"
    python sync_board.py

输出：
    board_snapshot/
    ├── ui/            desktop.py / fbui.py / apps_*.py / audio_alsa_svc.py ...
    ├── cloud_api.py   cloud-api 服务
    ├── boot/          只存 md5 指纹（不存 bit 本体）
    ├── etc/           配置
    └── MANIFEST.txt   全部文件清单 + md5
"""
import hashlib
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "board_snapshot")

# (远端路径, 本地相对路径)
FILES = [
    # ---- UI 层 ----
    ("/home/zynq/ui/desktop.py",               "ui/desktop.py"),
    ("/home/zynq/ui/fbui.py",                  "ui/fbui.py"),
    ("/home/zynq/ui/apps_music.py",            "ui/apps_music.py"),
    ("/home/zynq/ui/apps_music_new.py",        "ui/apps_music_new.py"),
    ("/home/zynq/ui/apps_scope_dual.py",       "ui/apps_scope_dual.py"),
    ("/home/zynq/ui/apps_scope.py",            "ui/apps_scope.py"),
    ("/home/zynq/ui/apps_scope_hub.py",        "ui/apps_scope_hub.py"),
    ("/home/zynq/ui/apps_wave_ai.py",          "ui/apps_wave_ai.py"),
    ("/home/zynq/ui/apps_agent.py",            "ui/apps_agent.py"),
    ("/home/zynq/ui/apps_notes.py",            "ui/apps_notes.py"),
    ("/home/zynq/ui/apps_settings.py",         "ui/apps_settings.py"),
    ("/home/zynq/ui/apps_sys.py",              "ui/apps_sys.py"),
    ("/home/zynq/ui/apps_calc.py",             "ui/apps_calc.py"),
    ("/home/zynq/ui/apps_files.py",            "ui/apps_files.py"),
    ("/home/zynq/ui/audio_alsa_svc.py",        "ui/audio_alsa_svc.py"),
    ("/home/zynq/ui/screen_guard.py",          "ui/screen_guard.py"),
    ("/home/zynq/ui/scope_dual.c",             "ui/scope_dual.c"),
    ("/home/zynq/ui/scope_capture_dataset.py", "ui/scope_capture_dataset.py"),
    # ---- 服务层 ----
    ("/home/zynq/cloud_api.py",                "cloud_api.py"),
    ("/home/zynq/thermal_guard.py",            "thermal_guard.py"),
    ("/home/zynq/infer_local.py",              "infer_local.py"),
    ("/home/zynq/wave_model_spec.json",        "wave_model_spec.json"),
    # ---- 配置（敏感，注意别公开仓库）----
    ("/etc/xiaobai-cloud.json",                "etc/xiaobai-cloud.json"),
]

# 只记录指纹（不拉本体）
FINGERPRINT = [
    "/mnt/boot/system.bit",
    "/mnt/boot/system.dtb",
    "/mnt/boot/BOOT.BIN",
    "/mnt/boot/zImage",
    "/home/zynq/wave_weights.bin",
]


def main():
    print("板子: %s" % board.HOST)

    if not board.conn():
        sys.exit("连不上板子，检查 BOARD_IP / 网络")

    os.makedirs(OUT, exist_ok=True)
    manifest = []
    ok = fail = 0

    # ---- 拉文件 ----
    for remote, rel in FILES:
        local = os.path.join(OUT, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        try:
            board.get(remote, local)
            if os.path.isfile(local):
                data = open(local, "rb").read()
                if len(data) > 0:
                    h = hashlib.md5(data).hexdigest()
                    manifest.append("%-52s %s  %8d B" % (rel, h, len(data)))
                    print("  ✅ %-42s %8d B  %s" % (rel, len(data), h[:10]))
                    ok += 1
                else:
                    print("  ⚠ %-42s (空)" % rel)
                    fail += 1
            else:
                print("  ⚠ %-42s (取不到)" % rel)
                fail += 1
        except Exception as e:
            print("  ❌ %-42s %s" % (rel, e))
            fail += 1

    # ---- 指纹 ----
    os.makedirs(os.path.join(OUT, "boot"), exist_ok=True)
    for remote in FINGERPRINT:
        try:
            out = board.run("md5sum %s 2>/dev/null; stat -c %%s %s 2>/dev/null"
                            % (remote, remote), timeout=20, quiet=True)
            if isinstance(out, tuple):
                out = out[1]
            lines = [l.strip() for l in (out or "").split("\n") if l.strip()]
            if lines:
                md5 = lines[0].split()[0]
                size = lines[1] if len(lines) > 1 else "?"
                name = os.path.basename(remote)
                rel = "boot/%s.md5" % name
                with open(os.path.join(OUT, rel.replace("/", os.sep)), "w") as f:
                    f.write("%s  %s  %s bytes\n" % (md5, remote, size))
                manifest.append("%-52s %s  %8s B" % (rel, md5, size))
                print("  🔑 %-42s md5=%s" % (name, md5[:12]))
        except Exception as e:
            print("  ❌ %-42s %s" % (remote, e))

    # ---- MANIFEST ----
    with open(os.path.join(OUT, "MANIFEST.txt"), "w", encoding="utf-8") as f:
        f.write("# board_snapshot 清单  %s\n\n" % board.HOST)
        for line in manifest:
            f.write(line + "\n")

    print()
    print("完成: %d 成功, %d 失败" % (ok, fail))
    print("目录: %s" % OUT)
    print()
    print("下一步:")
    print("  git diff board_snapshot/")
    print("  git add board_snapshot/")
    print('  git commit -m "board: 快照 <说明>"')


if __name__ == "__main__":
    main()
