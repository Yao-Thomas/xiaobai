echo "########## 1) UI 目录里和输入法/键盘相关的文件 ##########"
ls -la /home/zynq/ui/*.py | awk '{print "  " $5 "  " $9}'
echo
echo "########## 2) 找软键盘/中文输入法模块 ##########"
grep -ln "软键盘\|输入法\|pinyin\|拼音\|IMEW\|kb\b" /home/zynq/ui/*.py 2>/dev/null | head -10
echo
echo "########## 3) 浏览器应用 ##########"
ls -la /home/zynq/ui/apps_browser*.py 2>/dev/null
grep -nE "input|搜索|search|地址栏|url|键盘|kb" /home/zynq/ui/apps_browser.py 2>/dev/null | head -25