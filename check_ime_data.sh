#!/bin/bash
# 查板子上有没有可以拿来做"本地中文输入法"的数据
# 思路：espeak-ng 的中文数据是 汉字->拼音，反过来建索引就是 拼音->汉字
#       vosk 中文模型里有词表，可以用来给候选词排序
echo "===== 1) espeak-ng 的数据目录 ====="
for d in /usr/lib/*/espeak-ng-data /usr/share/espeak-ng-data /usr/lib/espeak-ng-data; do
  [ -d "$d" ] && echo "  存在: $d" && ls -la "$d" | head -20
done
echo
echo "===== 2) 跟中文(zh/cmn)相关的文件（espeak-ng 里拼音数据通常叫 zh_*）====="
find /usr/lib/*/espeak-ng-data /usr/share/espeak-ng-data -iname "*zh*" -o -iname "*cmn*" 2>/dev/null | head -20
echo
echo "===== 3) espeak-ng 版本与可用语音 ====="
espeak-ng --version 2>&1 | head -2
echo "--- 中文语音 ---"
espeak-ng --voices 2>/dev/null | grep -iE "zh|cmn|chinese" | head -10
echo
echo "===== 4) espeak-ng 源码包里的字典源文件（hanzi->pinyin 通常在这）====="
find / -name "zh_pinyin*" -o -name "zh_listx*" -o -name "zh_dict*" 2>/dev/null | head -10
find /usr/share -path "*espeak*" -name "*.txt" 2>/dev/null | head -10
echo
echo "===== 5) vosk 中文模型里的词表 ====="
ls -la /home/zynq/vosk-model-small-cn-0.22/ 2>/dev/null
echo "--- graph 目录 ---"
ls -la /home/zynq/vosk-model-small-cn-0.22/graph/ 2>/dev/null | head
echo "--- 词表大小 ---"
wc -l /home/zynq/vosk-model-small-cn-0.22/graph/words.txt 2>/dev/null
head -5 /home/zynq/vosk-model-small-cn-0.22/graph/words.txt 2>/dev/null
echo
echo "===== 6) 系统里有没有现成的拼音库 ====="
python3 -c "import pypinyin; print('  pypinyin', pypinyin.__version__)" 2>&1 | head -2
ls /usr/share/unicode 2>/dev/null | head -3
echo "--- 有没有中文字体（输入法要显示候选字）---"
fc-list 2>/dev/null | grep -icE "cjk|wqy|noto.*sc|zenhei|uming|ukai" | sed 's/^/  CJK 字体数: /'
fc-list 2>/dev/null | grep -iE "cjk|wqy|noto.*sc|zenhei" | head -3
echo
echo "===== 7) 我们用的界面字体是什么 ====="
grep -nE "ttf|otf|font" /home/zynq/ui/fbui.py 2>/dev/null | head -8
