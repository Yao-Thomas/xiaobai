#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_agent_api.py —— 修 /tools 的描述 + /status 的温度

1) /tools: tools.REGISTRY 的条目是 **dict**（{"name","desc","params","fn"}），
   我原来用 getattr(t, "desc") 取 —— dict 的键取不到，结果拿到了 dict 类的
   __doc__（"dict() -> new empty dictionary"）。改成 t.get("desc")。

2) /status: 温度一直缺 —— 原来的循环只看 /sys/class/thermal/thermal_zone0/temp。
   加上 hwmon 和 Zynq 的 XADC 备选路径。
"""
import io
import re
import sys

P = "agent/main.py"
src = io.open(P, encoding="utf-8").read()

# ---------------- 1) /tools 取描述 ----------------
start = src.find("    def _api_tools(self):")
if start == -1:
    sys.exit("找不到 _api_tools")
end = src.find("    API_DOC = [", start)
if end == -1:
    sys.exit("找不到 _api_tools 的结束位置")

new_fn = '''    def _api_tools(self):
        """工具清单。★ 条目是 dict：{"name","desc","params","fn"}"""
        out = []
        for name, t in sorted(tools.REGISTRY.items()):
            desc = ""
            params = None
            if isinstance(t, dict):
                desc = t.get("desc") or ""
                params = t.get("params")
                if not desc:
                    fn = t.get("fn")
                    d = getattr(fn, "__doc__", None)
                    if isinstance(d, str):
                        desc = d
            else:
                desc = getattr(t, "desc", "") or ""
            desc = (desc or "").strip().splitlines()[0][:180] if desc else ""
            item = {"name": name, "description": desc}
            if params:
                try:
                    props = params.get("properties") or {}
                    item["params"] = sorted(props.keys())
                    item["required"] = params.get("required") or []
                except Exception:
                    pass
            out.append(item)
        return {"ok": True, "count": len(out), "tools": out}

'''
src = src[:start] + new_fn + src[end:]
print("  OK: /tools 描述改为从 dict 取")

# ---------------- 2) /status 补温度 ----------------
old_temp = '''        for p in ("/sys/class/thermal/thermal_zone0/temp",):
            try:
                d["temp"] = round(int(open(p).read().strip()) / 1000.0, 1)
            except Exception:
                pass'''
new_temp = '''        # ★ 温度：Zynq 上有几种可能的位置，都试一遍
        for p in ("/sys/class/thermal/thermal_zone0/temp",
                  "/sys/class/hwmon/hwmon0/temp1_input",
                  "/sys/devices/soc0/amba/f8007100.adc/"
                  "iio:device0/in_temp0_raw"):
            try:
                raw = int(open(p).read().strip())
                d["temp"] = (round(raw / 1000.0, 1) if raw > 2000
                             else round(raw * 503.975 / 4096.0 - 273.15, 1))
                break
            except Exception:
                continue
        try:
            import subprocess
            d["kernel"] = subprocess.run(["uname", "-r"],
                                         stdout=subprocess.PIPE,
                                         timeout=5).stdout.decode().strip()
        except Exception:
            pass'''
if old_temp in src:
    src = src.replace(old_temp, new_temp, 1)
    print("  OK: /status 补上温度和内核版本")
else:
    print("  [!] 温度那段没匹配到（可能已改）")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("syntax OK")
