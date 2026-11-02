echo "=== 1) _top_bar 里所有 _btns.append（看矩形有没有异常大的）==="
grep -nE "_btns|self\.addr|exit_btn" /home/zynq/ui/apps_browser.py | head -20
echo
echo "=== 2) _btns 定义全文 ==="
sed -n '/def _top_bar/,/def _draw_input/p' /home/zynq/ui/apps_browser.py | grep -nE "append|addr|r =|r2 =|\[" | head -25
echo
echo "=== 3) tap() 里 addr 之前的分支 ==="
sed -n '/    def tap(self, x, y):/,/if fbui.hit(self.addr/p' /home/zynq/ui/apps_browser.py | head -40