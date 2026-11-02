cd /home/zynq/ui
python3 - <<'PYEOF'
import sys, urllib.parse
sys.path.insert(0, '/home/zynq/ui')
import webfetch as W

print("=== Result 类的字段 ===")
import inspect
src = inspect.getsource(W.Result) if hasattr(W, 'Result') else "(没有 Result 类)"
print(src[:600])

print()
print("=== 各引擎实测（中文查询 '现在'）===")
q = "现在"
engines = [
    ("Bing RSS",  "https://www.bing.com/search?q=%s&format=rss" % urllib.parse.quote(q)),
    ("DuckDuckGo","https://lite.duckduckgo.com/lite/?q=%s" % urllib.parse.quote(q)),
    ("Sogou",     "https://www.sogou.com/web?query=%s" % urllib.parse.quote(q)),
]
for name, url in engines:
    try:
        r = W.fetch(url, timeout=15, max_bytes=200*1024)
        # 取出正文字段
        body = ""
        for attr in ("text", "body", "html", "data", "content"):
            v = getattr(r, attr, None)
            if isinstance(v, str) and v:
                body = v; break
        if not body:
            body = str(r)
        print("  %-12s len=%-7d ctype=%s" % (name, len(body), getattr(r, "ctype", "?")))
        print("      ", body[:200].replace("\n", " "))
    except Exception as e:
        print("  %-12s 失败: %s: %s" % (name, type(e).__name__, e))
PYEOF