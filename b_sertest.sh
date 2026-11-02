cd /home/zynq/ui
echo "=== 1) 用浏览器自己的 webfetch 抓 Bing RSS（中文查询）==="
python3 - <<'PYEOF'
import sys
sys.path.insert(0, '/home/zynq/ui')
import webfetch as W
for q in ("zynq", "现在"):
    url = "https://www.bing.com/search?q=%s&format=rss" % __import__('urllib.parse', fromlist=['quote']).quote(q)
    try:
        r = W.fetch(url, timeout=15, max_bytes=200*1024)
        txt = r if isinstance(r, str) else (r[1] if isinstance(r, tuple) else str(r))
        print("  [%s] 抓到 %d 字符" % (q, len(txt)))
        print("      片段:", txt[:180].replace("\n"," ") if txt else "(空)")
    except Exception as e:
        print("  [%s] 失败: %s" % (q, e))
PYEOF
echo
echo "=== 2) 对比 DuckDuckGo ==="
python3 - <<'PYEOF'
import sys
sys.path.insert(0, '/home/zynq/ui')
import webfetch as W
try:
    r = W.fetch("https://lite.duckduckgo.com/lite/?q=zynq", timeout=10, max_bytes=100*1024)
    txt = r if isinstance(r, str) else (r[1] if isinstance(r, tuple) else str(r))
    print("  duckduckgo: 抓到 %d 字符" % len(txt))
    print("      片段:", (txt[:150].replace("\n"," ") if txt else "(空)"))
except Exception as e:
    print("  duckduckgo 失败: %s" % e)
PYEOF