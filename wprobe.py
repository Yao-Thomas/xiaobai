
import json, urllib.request
u = "http://wttr.in/Beijing?format=j1&lang=zh"
d = json.load(urllib.request.urlopen(u, timeout=20))
cc = d["current_condition"][0]
for k in ("temp_C", "FeelsLikeC", "humidity", "weatherDesc", "lang_zh",
          "windspeedKmph", "winddir16Point", "observation_time"):
    print("%-16s: %s" % (k, cc.get(k)))
w = d["weather"][0]
print("%-16s: %s / %s" % ("max/min", w.get("maxtempC"), w.get("mintempC")))
na = d.get("nearest_area")
if na:
    print("%-16s: %s / %s" % ("area/region",
                              na[0]["areaName"][0]["value"], na[0]["region"][0]["value"]))
print("json 大小约 %d 字节" % len(json.dumps(d)))
