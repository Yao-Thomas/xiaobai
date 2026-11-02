echo "########## 1) fbui.MiniKeyboard 的结构 ##########"
grep -nE "class MiniKeyboard|def press|def draw|KEYS|ROWS|ime|IME|候选|拼音" /home/zynq/ui/fbui.py | head -30
echo
echo "########## 2) 谁在用 ime_cn ##########"
grep -rn "ime_cn\|IME(" /home/zynq/ui/*.py | head -20
echo
echo "########## 3) apps_browser.py 里键盘相关 ##########"
grep -nE "kb|MiniKeyboard|ime|IME|input|press|候选|拼音|搜索|SEARCH" /home/zynq/ui/apps_browser.py | head -30
echo
echo "########## 4) 数据表在不在 ##########"
ls -la /home/zynq/ui/ime_cn.json 2>/dev/null || echo "  ✗ ime_cn.json 不存在"