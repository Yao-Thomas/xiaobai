echo "=== 1) fbui.btn 和 scr.tw 的签名 ==="
grep -nE "^def btn|^    def tw|def tw\(" /home/zynq/ui/fbui.py | head -5
sed -n '/^def btn/,/^    return/p' /home/zynq/ui/fbui.py | head -18
echo "--- tw ---"
grep -n "def tw" -A 10 /home/zynq/ui/fbui.py | head -14
echo
echo "=== 2) 手动构造 browser 对象，直接调 _draw_input 看有没有异常 ==="
cd /home/zynq/ui
sudo python3 - <<'PYEOF' 2>&1 | tail -25
import sys
sys.path.insert(0, '/home/zynq/ui')
import fbui
import apps_browser as B

class FakeScr:
    w, h = 1024, 600
    def rect(self,*a,**k): pass
    def rrect(self,*a,**k): pass
    def text(self,*a,**k): pass
    def tw(self, t, size, cn=False):
        return len(t) * (size if cn else size//2)
    def clear(self,*a,**k): pass
    def flush(self): pass

class FakeTouch:
    def poll(self, move=False): return None
    exit_zone = None

try:
    b = B.Browser(FakeScr(), FakeTouch())
    print("  构造 OK")
    print("  ime:", b.ime, "ok=", getattr(b.ime,'ok',None))
    b.kb = fbui.MiniKeyboard(y0=B.KB_Y, key_w=76, key_h=B.KB_KH, gap=B.KB_GAP)
    b.input = "test"
    b.py = "xianzai"
    b.refresh_cands()
    print("  候选:", b.cands[:4])
    print("  cand_items 数量:", len(b.cand_items(b.scr)))
    b._draw_input()
    print("  _draw_input() 无异常 ✓")
except Exception as e:
    import traceback
    traceback.print_exc()
PYEOF