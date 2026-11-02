
import sys, time
sys.path.insert(0, "/home/zynq/ui")
from PIL import Image, ImageDraw
import fbui
class FS(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0; self.gpu = None; self.mode = "BGR;24"
        self._fast = True; self.yoff = 0
        self.img = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
    def flush(self, box=None): pass
fbui.Screen = FS
import apps_novel as N
scr = FS()
p = sys.argv[1]
t0 = time.time(); raw = open(p, "rb").read(); t1 = time.time()
txt, enc = N._decode(raw); txt = N._norm(txt); t2 = time.time()
cpl, lpp, lh = N.metrics(scr, 24)
t3 = time.time(); starts = N.paginate(txt, cpl, lpp); t4 = time.time()
print("  读文件 %.0fms | 解码 %.0fms | 分页 %.0fms | 共 %d 页 | 编码 %s"
      % ((t1-t0)*1000, (t2-t1)*1000, (t4-t3)*1000, len(starts), enc))
r = N.Reader(p)
t0 = time.time(); r.layout(scr); N.draw_reader(scr, r); t1 = time.time()
print("  首屏渲染 %.0fms" % ((t1-t0)*1000))
t0 = time.time()
for k in range(20):
    r.page += 1
    N.draw_reader(scr, r)
t1 = time.time()
print("  翻页 平均 %.1f ms/页" % ((t1-t0)*1000/20))
