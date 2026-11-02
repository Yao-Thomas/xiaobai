echo "=== fbui.Touch._load_inject 全文 ==="
sed -n '/def _load_inject/,/def poll/p' /home/zynq/ui/fbui.py
echo
echo "=== poll 全文 ==="
sed -n '/def poll(self, move=False)/,/^    def /p' /home/zynq/ui/fbui.py | head -45