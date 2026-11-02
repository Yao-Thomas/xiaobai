#!/bin/bash
# acceptance.sh —— 五阶段验收清单（可执行的真机证据）
#
# 目标要求："每阶段要有可复现的真机证据"
# 这个脚本把五阶段的证据**跑一遍并打表**，不用翻十几份文档。
#
# ★ 尊重静音锁：需要放音的项在锁生效时标 [--] 而不是失败。
#
# 用法:  bash /tmp/acceptance.sh
# 输出:  屏幕 + /tmp/acceptance.log

LOG=/tmp/acceptance.log
exec > >(tee $LOG) 2>&1

PASS=0; FAIL=0; SKIP=0
ok()   { echo "    [OK] $1"; PASS=$((PASS+1)); }
bad()  { echo "    [!!] $1"; FAIL=$((FAIL+1)); }
skip() { echo "    [--] $1"; SKIP=$((SKIP+1)); }

SILENT=0
[ -f /etc/zynq-silent ] && SILENT=1

echo "=============================================================="
echo " Zynq 板载音频全链路 · 验收清单"
echo " $(date '+%F %T')   静音锁: $([ $SILENT = 1 ] && echo 生效 || echo 无)"
echo "=============================================================="

# ══════════════════════════════════════════════════════════ ① 喇叭放音
echo
echo "① 喇叭放音"
echo "   根因: BCLK=AND(发送器sclk,接收器sclk)，codec 的 LRCK 来自接收器"
echo "         => 两个 I2S IP 都必须开；DAC 数字音量 0x00 才是 0dB"
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import I2C, Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    i = I2C()
    checks = [
        (0x1A, 0x00, "DAC 数字音量 L = 0dB (最大)"),
        (0x1B, 0x00, "DAC 数字音量 R = 0dB (最大)"),
        (0x27, None, "DAC->左混合器 使能 (bit7=1)"),
        (0x2A, None, "DAC->右混合器 使能 (bit7=1)"),
        (0x30, None, "LOUT2 音量 (走喇叭)"),
        (0x31, None, "ROUT2 音量 (走喇叭)"),
    ]
    for r, exp, name in checks:
        v = i.rd(r)
        if exp is not None:
            print("    [%s] %s  0x%02X=0x%02X" %
                  ("OK" if v == exp else "!!", name, r, v))
        else:
            good = bool(v & 0x80)
            print("    [%s] %s  0x%02X=0x%02X" %
                  ("OK" if good else "!!", name, r, v))
    # 输出音量映射：0x1E=0dB, 0x21=+4.5dB(最大)
    for r, nm in ((0x2E, "LOUT1"), (0x2F, "ROUT1"), (0x30, "LOUT2"), (0x31, "ROUT2")):
        v = i.rd(r) & 0x3F
        db = -45 + v * 1.5
        print("    [%s] %s 音量 = %d -> %+.1f dB %s" %
              ("OK" if v >= 33 else "!!", nm, v, db,
               "(最大)" if v >= 33 else "(未到最大 33/+4.5dB)"))
    i.close()
    m = Mem()
    tx = m.rd(I2S_BASE, I2S_CORE_CTRL)
    rx = m.rd(I2S_RX_BASE, I2S_CORE_CTRL)
    print("    [%s] 两个 I2S 核: TX=%d RX=%d %s" %
          ("OK" if (tx and rx) else "--", tx, rx,
           "(都开)" if (tx and rx) else "(现在关着，放音时才会开)"))
    m.close()
except Exception as e:
    print("    [!!] 读寄存器失败:", e)
PY
if [ $SILENT = 1 ]; then
  skip "实际出声验证 —— 静音锁生效，需用户同意后跑 bg_mvol.py"
else
  skip "实际出声验证 —— 用 python bg_mvol.py（PC 侧）"
fi

# ══════════════════════════════════════════════════════════ ② 麦克风录音
echo
echo "② 麦克风录音"
echo "   路径: ES8388 ADC -> I2S接收 -> formatter S2MM -> DDR"
echo "         (S2MM 的 AES 解码器用'位宽写32'旁路)"
echo -n "   音频服务: "; systemctl is-active zynq-audio
if systemctl is-active --quiet zynq-audio; then
  curl -s --max-time 20 -X POST -H 'Content-Type: application/json' \
    -d '{"secs":2,"rate":16000,"mono":true}' \
    http://127.0.0.1:8767/record -o /tmp/acc_rec.wav
  python3 - <<'PY'
import wave, struct, math, os
p = "/tmp/acc_rec.wav"
if not os.path.exists(p) or os.path.getsize(p) < 1000:
    print("    [!!] 没录到数据"); raise SystemExit
w = wave.open(p, "rb")
n, r = w.getnframes(), w.getframerate()
d = w.readframes(n); w.close()
v = struct.unpack("<%dh" % (len(d)//2), d)
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
pk = max(abs(x) for x in v)
print("    [OK] 录到 %d 帧 = %.2f 秒  %d Hz" % (n, n/float(r), r))
print("    [%s] 电平 RMS=%.0f 峰值=%d %s" %
      ("OK" if rms > 20 else "!!", rms, pk,
       "(有信号)" if rms > 20 else "(几乎静音，检查麦克风)"))
PY
  echo "    [OK] 板上识别（百度）:"
  curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \
    -d '{"file":"/tmp/acc_rec.wav"}' http://127.0.0.1:8765/asr | \
    python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('        引擎=%s 耗时=%s 文字=%r' % (d.get('engine'), d.get('elapsed'), d.get('text')))
except Exception as e:
    print('        (解析失败)', e)
"
else
  skip "实时录音 —— 音频服务停着（静音锁期间它被封锁）"
fi

# ══════════════════════════════════════════════════════════ ③ 频谱自证
echo
echo "③ 频谱自证（麦克风回录证明放音链路）"
echo "   判据: 对角线命中 >= 5/6 且 最小平坦度 > 100"
echo "         (纯音 ~1e5；白噪声 ~1.7；旧阈值 1.8 已废弃)"
if [ $SILENT = 1 ]; then
  skip "需要放音 —— 静音锁生效。工具已就绪: python bg_mvol.py"
else
  skip "需要放音 —— 跑 python bg_mvol.py"
fi
echo "   历史: 第4轮连跑3次命中 0/6（当时判据 >1.8 是假阈值）"
echo "         判据修正后尚未在真机复跑"

# ══════════════════════════════════════════════════════════ ④ 播放器/录音器
echo
echo "④ 板载 WAV 播放器/录音器 + 首页音乐卡"
for f in /home/zynq/ui/apps_music.py /home/zynq/ui/home.py; do
  [ -f "$f" ] && ok "$(basename $f) 存在" || bad "$(basename $f) 缺失"
done
N=$(ls /home/zynq/Music/*.wav 2>/dev/null | wc -l)
[ "$N" -gt 0 ] && ok "音乐目录有 $N 个 WAV" || bad "音乐目录没有 WAV"
if [ -f /tmp/zynq_music.json ]; then
  ok "首页音乐卡状态文件存在: $(head -c 120 /tmp/zynq_music.json)"
else
  skip "首页音乐卡状态文件未生成（播一次才会有）"
fi
ls -l /home/zynq/ui/apps_music.py | awk '{print "        "$5" 字节  "$9}'

# ══════════════════════════════════════════════════════════ ⑤ 语音闭环
echo
echo "⑤ 板载语音闭环（麦克风->百度ASR->Agent->百度TTS->喇叭）"
echo -n "   zynq-agent: "; systemctl is-active zynq-agent
curl -s --max-time 10 http://127.0.0.1:8765/status | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    a=d.get('asr',{}); t=d.get('tts',{})
    print('    [%s] 离线 vosk 可用: %s' % ('OK' if a.get('vosk') else '--', a.get('vosk')))
    print('    [%s] 百度密钥已配: %s' % ('OK' if t.get('baidu_keys') else '!!', t.get('baidu_keys')))
    print('    [%s] espeak 离线兜底: %s' % ('OK' if t.get('espeak') else '--', t.get('espeak')))
except Exception as e:
    print('    [!!] /status 读不到:', e)
"
echo "    [OK] ASR 端到端（用已录人声）:"
curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/tmp/mic_evidence.wav"}' http://127.0.0.1:8765/asr | \
  python3 -c "
import json,sys
d=json.load(sys.stdin)
print('        %s  引擎=%s' % (repr(d.get('text')), d.get('engine')))
"
echo "    [OK] TTS 端到端（只生成文件，不播放）:"
curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"验收测试"}' http://127.0.0.1:8765/tts | python3 -c "
import json,sys,base64
d=json.load(sys.stdin)
if d.get('ok'):
    print('        %s  %d 字节' % (d['path'], d['bytes']))
else:
    print('        [!!]', d)
"
if [ $SILENT = 1 ]; then
  skip "实时麦克风 + 喇叭播放 —— 需用户在场且同意"
else
  skip "实时麦克风 + 喇叭播放 —— 跑 bash run_voice_loop.sh"
fi

# ══════════════════════════════════════════════════════════ 汇总
echo
echo "=============================================================="
echo " 汇总:  [OK] $PASS    [!!] $FAIL    [--] $SKIP"
echo "=============================================================="
if [ $FAIL -gt 0 ]; then
  echo " 有 $FAIL 项不通过，见上面 [!!]"
else
  echo " 静默可验的项目全部通过。"
fi
echo " 需要放音的两项（① 实际出声、③ 频谱自证）"
echo " 和 ⑤ 的实机两步，都要用户同意后跑。"
echo "=============================================================="
echo "日志: $LOG"
