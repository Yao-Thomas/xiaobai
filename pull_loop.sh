#!/bin/bash
# 把闭环验证的产物拉出来看看
ls -l /tmp/xiaobai_say.wav /tmp/mic_evidence.wav 2>/dev/null
cp /tmp/xiaobai_say.wav /tmp/loop_tts_out.wav 2>/dev/null
echo "TTS 输出已准备: /tmp/loop_tts_out.wav"