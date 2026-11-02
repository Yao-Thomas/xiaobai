#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把音频这套东西部署到板子，备好"听音测试"的全部条件。

上传:
    ui/audio_pl.py          -> /home/zynq/ui/audio_pl.py
    ui/test_audio.sh        -> /home/zynq/test_audio.sh
    _testwav/*.wav          -> /home/zynq/Music/
    ui/home.py              -> 不动（首页那张音乐卡已经在等 WAV 了）

用法:
    python deploy_audio.py            # 部署 + 跑一次 --diag（不出声）
    python deploy_audio.py --sound    # 部署 + 直接开始引导式听音
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402
import broot                       # noqa: E402

UI = os.path.join(HERE, "ui")
WAVS = os.path.join(HERE, "_testwav")


def upload_user(local, remote, mode="0644"):
    tmp = "/tmp/_dep_" + os.path.basename(local)
    board.put(local, tmp)
    broot.srun("install -o zynq -g zynq -m %s %s %s" % (mode, tmp, remote),
               quiet=True)
    print("   %-42s <- %s" % (remote, os.path.basename(local)))


def main():
    print("HOST =", board.HOST)

    print("\n--- 1) 建目录")
    broot.srun("install -d -o zynq -g zynq -m 0755 /home/zynq/Music",
               quiet=True)

    print("\n--- 2) 传文件")
    upload_user(os.path.join(UI, "audio_pl.py"), "/home/zynq/ui/audio_pl.py")
    upload_user(os.path.join(UI, "beep.py"), "/home/zynq/ui/beep.py")
    upload_user(os.path.join(UI, "test_audio.sh"), "/home/zynq/test_audio.sh",
                "0755")
    n = 0
    if os.path.isdir(WAVS):
        for fn in sorted(os.listdir(WAVS)):
            if fn.lower().endswith(".wav"):
                upload_user(os.path.join(WAVS, fn),
                            "/home/zynq/Music/" + fn)
                n += 1
    print("   共传 %d 个 wav" % n)

    print("\n--- 3) 核对 md5")
    import hashlib
    for local, remote in [(os.path.join(UI, "audio_pl.py"),
                           "/home/zynq/ui/audio_pl.py"),
                          (os.path.join(UI, "test_audio.sh"),
                           "/home/zynq/test_audio.sh")]:
        h = hashlib.md5(open(local, "rb").read()).hexdigest()
        out, _ = broot.srun("md5sum %s" % remote, quiet=True)
        got = out.split()[0] if out.strip() else "?"
        print("   %-38s %s %s" % (remote, got, "OK" if got == h else
                                  "!! 期望 " + h))

    print("\n--- 4) 清掉 /tmp 里的旧副本（原来只放 /tmp，重启就没了）")
    broot.srun("rm -f /tmp/audio_pl.py /tmp/_ag_*.py", quiet=True)

    print("\n--- 5) 只读自检（不出声）")
    broot.srun("cd /home/zynq/ui && python3 -u audio_pl.py", use_sudo=False)

    print("\n--- 6) 目录确认")
    broot.srun("ls -l /home/zynq/ui/audio_pl.py /home/zynq/test_audio.sh "
               "/home/zynq/Music/", use_sudo=False)

    print("""
============================================================
 都准备好了。你回来只要跑一条命令：

     bash /home/zynq/test_audio.sh

 它会：
   1. 打印 formatter / I2S / ES8388 寄存器（确认硬件在位）
   2. 用 4 种配置各播一个**不同音高**的正弦（500/1000/2000/4000 Hz），
      听清哪个音高，就说明哪种配置是对的
   3. 全程写进 /home/zynq/audio_test.log

 或者直接：
     bash /home/zynq/test_audio.sh motif      # C-E-G-C
     bash /home/zynq/test_audio.sh 03_小星星.wav
============================================================
""")


if __name__ == "__main__":
    main()
    if "--sound" in sys.argv:
        print("\n--- 开始引导式听音 ---")
        broot.srun("cd /home/zynq/ui && python3 -u audio_pl.py --guided --vol 33",
                   use_sudo=False, timeout=300)
