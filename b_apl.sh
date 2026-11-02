echo "=== audio_pl.py 的对外接口 ==="
grep -nE "^def |^class |    def " /home/zynq/ui/audio_pl.py | head -40
echo
echo "=== 录音相关的函数 ==="
grep -nE "def .*(rec|cap|read|dma|start|stop)" /home/zynq/ui/audio_pl.py | head -20
echo
echo "=== 模块开头的用法说明 ==="
head -40 /home/zynq/ui/audio_pl.py