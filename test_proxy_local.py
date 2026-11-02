import urllib.request, urllib.error, http.cookiejar, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
# 1) 不带口令
try:
    urllib.request.urlopen("http://127.0.0.1:3081/", timeout=6)
    print("1) 不带口令 -> 竟然通了（不对）")
except urllib.error.HTTPError as e:
    print("1) 不带口令 ->", e.code, "（预期的口令门）")
# 2) 带口令，不自动跳转，看 Set-Cookie
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedirect)
try:
    op.open("http://127.0.0.1:3081/?k=test1234", timeout=6)
except urllib.error.HTTPError as e:
    print("2) 带口令 ->", e.code, "Location:", e.headers.get("Location"))
    sc = e.headers.get_all("Set-Cookie") or []
    for c in sc: print("   Set-Cookie:", c[:70], "...")
# 3) 用 cookie 走完整流程
cj = http.cookiejar.CookieJar()
op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op2.open("http://127.0.0.1:3081/?k=test1234", timeout=6)
r = op2.open("http://127.0.0.1:3081/", timeout=10)
body = r.read(300)
print("3) 带 cookie 请求首页 ->", r.status, r.headers.get("Content-Type"))
print("   页面开头:", body[:90].decode("utf-8","replace").replace("\n"," "))
print()
print("   [OK] 代理链路完全打通" if r.status == 200 else "   [X] 失败")