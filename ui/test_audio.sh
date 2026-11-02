#!/bin/bash
# test_audio.sh —— 一条命令做完音频听音测试，并把结果写进日志
#
# 用法（在板子上）:
#   bash /home/zynq/test_audio.sh            # 引导式：4 种配置各播一个不同音高
#   bash /home/zynq/test_audio.sh motif      # 直接播 C-E-G-C
#   bash /home/zynq/test_audio.sh 小星星      # 播小星星（要先放 WAV 到 ~/Music）
#   bash /home/zynq/test_audio.sh buzzer     # ★ 只试蜂鸣器（和音频链路无关）
#   bash /home/zynq/test_audio.sh diag       # 只打印寄存器/解码，不出声
#
# 结果同时写到 /home/zynq/audio_test.log
#
# ★ 分清两样东西：
#     背面【喇叭】  ← ES8388 LOUT2 → MD8002A 功放   —— 这是我们要测的音频链路
#     背面【蜂鸣器】← PL GPIO，Linux 里是个叫 beep 的输入设备  —— 和音频无关！
#   蜂鸣器响 ≠ 音频通。音频通的标志是能听出 500/1000/2000/4000 Hz 的**音高**。

# ★ 必须 root：要直接 mmap /dev/mem（PL 寄存器）和 /dev/i2c-1（ES8388）
if [ "$(id -u)" != "0" ]; then
    echo "需要 root（要碰 /dev/mem 和 /dev/i2c-1），用 sudo 重新跑一次 ..."
    exec sudo -p '[sudo] 密码: ' bash "$0" "$@"
fi

LOG=/home/zynq/audio_test.log
cd /home/zynq/ui || exit 1

run() {
    echo
    echo "############ $* ############"
    python3 -u "$@" 2>&1
    echo "rc=$?"
}

{
    echo "==================================================="
    echo " 音频听音测试   $(date '+%Y-%m-%d %H:%M:%S')"
    echo "==================================================="

    case "${1:-guided}" in
        buzzer)
            echo "--- 只测蜂鸣器（PL GPIO，跟音频链路无关）"
            run beep.py 2 300
            exit 0
            ;;
    esac

    # ★ 先 --codec（初始化 ES8388）再 --diag，
    #   否则 diag 打的是还没初始化的原始寄存器，一堆"不一致"看着吓人
    run audio_pl.py --codec
    run audio_pl.py --diag

    # 先用蜂鸣器打个「开始」的记号 —— 听到嘀说明你人在这儿、
    # 而且心里要清楚：嘀的是蜂鸣器，不是下面的正弦音
    echo
    echo "--- 先响一下【蜂鸣器】当开始记号（这不是音频链路！）"
    python3 -u beep.py 1 250 2>&1 || echo "(蜂鸣器没响，不影响继续)"

    case "${1:-guided}" in
        diag)   ;;
        motif)  run audio_pl.py --motif --vol 33 ;;
        tone)   run audio_pl.py --tone "${2:-1000}" "${3:-3}" --vol 33 ;;
        *)
            WAV="$1"
            if [ -z "$WAV" ] || [ "$WAV" = "guided" ]; then
                run audio_pl.py --guided --vol 33
            else
                # 支持直接给文件路径或 ~/Music 里的名字
                [ -f "$WAV" ] || WAV="/home/zynq/Music/$WAV"
                [ -f "$WAV" ] || WAV="/home/zynq/Music/$1.wav"
                if [ -f "$WAV" ]; then
                    run audio_pl.py --wavinfo "$WAV"
                    run audio_pl.py --play "$WAV" --vol 33
                    run audio_pl.py --play "$WAV" --vol 33 --pack lj
                else
                    echo "找不到文件: $1"
                    ls -l /home/zynq/Music/
                fi
            fi
            ;;
    esac

    echo
    echo "==================================================="
    echo " 结束。日志: $LOG"
    echo "==================================================="
} 2>&1 | tee "$LOG"
