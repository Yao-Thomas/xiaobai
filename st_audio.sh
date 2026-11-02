#!/bin/bash
# 免耳朵自检：放 1kHz 同时录，分别看 L / R / 和 / 差 四路的响应
B=http://127.0.0.1:8767
echo "=== selftest 1000Hz ==="
curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \
     -d '{"freq":1000,"secs":1.2}' $B/selftest > /tmp/st.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/st.json"))
print("cap_mode=%s  rate=%.0f/%.0f  判定=%s" %
      (d.get("cap_mode"), d.get("rate_quiet",0), d.get("rate_tone",0),
       d.get("verdict")))
print("%-6s %10s %10s %10s %10s %8s" %
      ("声道","静RMS","响RMS","静@1k","响@1k","比值dB"))
for m in ("L","R","sum","diff"):
    c = d["per_channel"][m]
    print("%-6s %10.1f %10.1f %10.1f %10.1f %+8.1f" %
          (m, c["rms_quiet"], c["rms_tone"], c["goe_quiet"], c["goe_tone"],
           c["ratio_db"]))
PY
