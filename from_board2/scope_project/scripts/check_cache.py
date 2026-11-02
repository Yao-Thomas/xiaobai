import sys, time
sys.path.insert(0, "/home/zynq/ui")
from fbui import Screen, Touch
import apps_scope_dual as A
scr = Screen(); scr.flush = lambda box=None: None
app = A.App(scr); app.make_bg()
for _ in range(40):
    app.step(); time.sleep(0.004)

# 1) 数值变化时 draw_stat 是否真的重画
app.m.m[0]["vpp"] = 1.23
app.draw_stat()
h1 = hash(app.scr.img.crop((88, A.ST1[1], 300, A.ST1[3])).tobytes())
app.m.m[0]["vpp"] = 9.99
app.draw_stat()
h2 = hash(app.scr.img.crop((88, A.ST1[1], 300, A.ST1[3])).tobytes())
print("  draw_stat 数值变化后重画:", "OK" if h1 != h2 else "FAIL 画面没更新!")

# 2) 时基变化时 draw_scales 是否重画
app.draw_scales()
h3 = hash(app.scr.img.crop((0, A.PLOT[3], 1024, A.PLOT[3]+30)).tobytes())
app.m.tb_index = (app.m.tb_index + 3) % len(A.TIMEBASES) if hasattr(A, "TIMEBASES") else app.m.tb_index
app._sc_key = None
app.draw_scales()
h4 = hash(app.scr.img.crop((0, A.PLOT[3], 1024, A.PLOT[3]+30)).tobytes())
print("  draw_scales 时基变化后重画:", "OK" if h3 != h4 else "(内容可能相同, 无法判定)")

# 3) 顶栏运行/暂停切换是否重画
app.draw_top()
h5 = hash(app.scr.img.crop((0, 0, A.W, A.TOP_H)).tobytes())
app.m.running = not app.m.running
app.draw_top()
h6 = hash(app.scr.img.crop((0, 0, A.W, A.TOP_H)).tobytes())
print("  draw_top 运行状态切换后重画:", "OK" if h5 != h6 else "FAIL 画面没更新!")

# 4) 连续跑 200 帧不报错
try:
    for _ in range(200):
        app.step(); app.draw_wave(); app.draw_stat(); app.draw_top(); app.draw_scales()
    print("  连续 200 帧无异常: OK")
except Exception as e:
    print("  连续 200 帧异常:", e)
print("CACHE_DONE")
