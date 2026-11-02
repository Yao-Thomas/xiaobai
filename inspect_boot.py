import re, sys, urllib.request, http.cookiejar
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open("http://127.0.0.1:3081/?k=xb7k2m9q", timeout=6)
r = op.open("http://127.0.0.1:3081/", timeout=10)
html = r.read().decode("utf-8", "replace")
print("页面大小:", len(html))
print()
print("=== 页面里出现的 127.0.0.1 / localhost / ws:// ===")
for pat in (r"127\.0\.0\.1[^\"'<> ]*", r"ws://[^\"'<> ]*", r"wss://[^\"'<> ]*",
            r"localhost[^\"'<> ]*", r"3080", r"3081"):
    hits = sorted(set(re.findall(pat, html)))[:8]
    if hits:
        print("  %-22s -> %s" % (pat, hits))
print()
print("=== __DSH_BOOT__ 内容（前 1200 字符）===")
m = re.search(r"__DSH_BOOT__\s*=\s*(\{.*?\});", html, re.S)
if m:
    print(m.group(1)[:1200])
else:
    m2 = re.search(r"__DSH_BOOT__[^<]{0,800}", html)
    print(m2.group(0)[:800] if m2 else "没找到")