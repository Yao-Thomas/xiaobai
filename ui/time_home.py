
import sys, time
from PIL import Image, ImageDraw
import fbui

class FakeScreen(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0; self.gpu = None; self.mode = "BGR;24"
        self._fast = True; self.yoff = 0
        self.img = Image.new("RGB", (self.w, self.h), (12, 16, 32))
        self.d = ImageDraw.Draw(self.img)
    def flush(self, box=None):
        pass

fbui.Screen = FakeScreen
import home
home.Screen = FakeScreen
scr = FakeScreen()
h = home.Home(scr, apps=[], icons={})
h.wall = h.make_wallpaper()

t0 = time.time(); h.build_static(); t1 = time.time()
print("build_static(壁纸+6卡玻璃+投影+Dock): %.0f ms" % ((t1-t0)*1000))
h.register_parts()
t0 = time.time(); h.draw(full=True); t1 = time.time()
print("首帧整屏绘制+flush:                    %.0f ms" % ((t1-t0)*1000))
h.info.dt = h.info.dt.replace(second=(h.info.dt.second+1) % 60)
h.info.cpu = (h.info.cpu + 3) % 100
t0 = time.time(); n = h.draw(full=False); t1 = time.time()
print("脏区重画 %d 块:                        %.0f ms" % (n, (t1-t0)*1000))
t0 = time.time()
for k in range(10):
    h.info.dt = h.info.dt.replace(second=(h.info.dt.second+1) % 60)
    h.draw(full=False)
t1 = time.time()
print("纯时钟刷新 平均:                       %.1f ms/帧" % ((t1-t0)*100))
