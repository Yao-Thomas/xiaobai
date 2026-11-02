cd /home/zynq/ui
python3 - <<'PYEOF'
import sys, urllib.parse
sys.path.insert(0, '/home/zynq/ui')
import webfetch as W

q = "现在"
for name, url in [
    ("Bing RSS",  "https://www.bing.com/search?q=%s&format=rss" % urllib.parse.quote(q)),
    ("DuckDuckGo","https://lite.duckduckgo.com/lite/?q=%s" % urllib.parse.quote(q)),
    ("Sogou",     "https://www.sogou.com/web?query=%s" % urllib.parse.quote(q)),
]:
    r = W.fetch(url, timeout=15, max_bytes=200*1024)
    t = r.text() if r.ok else ""
    print("  %-12s ok=%-5s ctype=%-24s bytes=%-7d err=%s" %
          (name, r.ok, r.ctype[:24], len(r.data), r.err or "-"))
    if t:
        print("      前 160 字:", t[:160].replace("\n", " "))
    print()
PYEOF