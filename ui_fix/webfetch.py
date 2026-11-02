#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webfetch.py —— 给浏览器用的抓取层

★ 板子上的坑（实测）：Python 用系统 CA 包会 `CERTIFICATE_VERIFY_FAILED:
  unable to get local issuer certificate` —— 文件在 /etc/ssl/certs/ca-certificates.crt，
  但 Python 找不到/用不了。所以这里做三级降级：
    1) 正常 TLS（用系统 CA）
    2) 显式指定 CA 文件
    3) 不校验证书（这台设备是玩具，可用性优先）
  哪一级成功就记住，后面复用。

其它：超时、重定向限制、gzip 解压、robots 不管、UA 伪装成普通浏览器、
     只收 text/* 和图片。
"""
import gzip
import io
import os
import re
import ssl
import socket
import urllib.request
import urllib.parse
import urllib.error

UA = ("Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/100.0 Safari/537.36")
TIMEOUT = 20
MAX_BYTES = 3 * 1024 * 1024
CAFILES = ["/etc/ssl/certs/ca-certificates.crt",
           "/etc/pki/tls/certs/ca-bundle.crt",
           "/etc/ssl/cert.pem"]

_SSL_MODE = None      # None=未定; "sys" / "cafile" / "none"
_OPENER = None


def _mk_opener(mode):
    if mode == "sys":
        ctx = ssl.create_default_context()
    elif mode == "cafile":
        ctx = None
        for c in CAFILES:
            if os.path.exists(c):
                ctx = ssl.create_default_context(cafile=c)
                break
        if ctx is None:
            ctx = ssl._create_unverified_context()
    else:
        ctx = ssl._create_unverified_context()
    h = urllib.request.HTTPSHandler(context=ctx)
    op = urllib.request.build_opener(h)
    op.addheaders = [("User-Agent", UA),
                     ("Accept", "text/html,application/xhtml+xml,image/*,*/*;q=0.8"),
                     ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
                     ("Accept-Encoding", "gzip, identity")]
    return op


def norm_url(u, base=None):
    """把用户输入变成可用 URL；'关键词' 走默认搜索引擎"""
    u = (u or "").strip()
    if base:
        u = urllib.parse.urljoin(base, u)
    if not u:
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        return u
    if u.startswith("//"):
        return "http:" + u
    # 像域名就直接补 http://
    if re.match(r"^[\w-]+(\.[\w-]+)+(/|$|\?)", u):
        return "http://" + u
    # ★ 2026-10-01: 改用 search_url()（SEARCH 现在是带 %s 的模板，不能再直接拼）
    return search_url(u)


# ★ 2026-10-01 修复：默认搜索引擎从 DuckDuckGo 换成必应 RSS。
#
#   原因：lite.duckduckgo.com 在国内**完全不可达**（Errno 101 Network unreachable），
#   而 apps_browser.py 的文档里写的就是"搜索走必应的 RSS 输出" —— 也就是说
#   这个常量本来就和设计不符（browser 里那个 SEARCH 常量是死代码，没被用）。
#
#   实测（中文查询「现在」）：
#     Bing RSS    ok=True   text/xml    5.4 KB   <title>必应：现在</title>  ✓
#     DuckDuckGo  ok=False  0 字节      [Errno 101]                          ✗
#     Sogou       ok=True   text/html   638 KB   （能用但页面巨大，要解析 HTML）
#
#   选必应 RSS 的理由：可达 + 中文查询可用 + 返回静态 XML（浏览器已有 RSS 解析）
#   + 体积小（快）。
SEARCH = "https://www.bing.com/search?q=%s&format=rss"


def search_url(q):
    """关键词 -> 搜索 URL（走上面的默认引擎）"""
    return SEARCH.replace("%s", urllib.parse.quote(q or ""))


class Result(object):
    def __init__(self, url, ctype, data, err=""):
        self.url = url
        self.ctype = ctype or ""
        self.data = data or b""
        self.err = err

    @property
    def ok(self):
        return not self.err and bool(self.data)

    def text(self, enc=None):
        return decode(self.data, self.ctype, enc)


def decode(data, ctype="", enc=None):
    """先按 HTTP 头/meta 声明猜，再按常见中文编码依次试"""
    cands = []
    if enc:
        cands.append(enc)
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    if m:
        cands.append(m.group(1).lower())
    head = data[:2048].decode("ascii", "ignore")
    m = re.search(r'charset\s*=\s*["\']?([\w-]+)', head, re.I)
    if m:
        cands.append(m.group(1).lower())
    cands += ["utf-8", "gb18030", "big5", "utf-16"]
    for c in cands:
        try:
            c = {"gbk": "gb18030", "gb2312": "gb18030"}.get(c, c)
            t = data.decode(c)
            if c in ("gb18030", "big5") and t[:3000].count("\ufffd") > 12:
                continue
            return t
        except Exception:
            continue
    return data.decode("utf-8", "replace")


def fetch(url, timeout=TIMEOUT, max_bytes=MAX_BYTES):
    """抓一个 URL；失败返回 Result(err=...)"""
    global _SSL_MODE, _OPENER
    if not url:
        return Result(url, "", b"", "空 URL")

    modes = [_SSL_MODE] if _SSL_MODE else ["sys", "cafile", "none"]
    last = ""
    for mode in modes:
        if mode is None:
            continue
        try:
            op = _OPENER if (_OPENER is not None and _SSL_MODE == mode) else _mk_opener(mode)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            r = op.open(req, timeout=timeout)
            data = r.read(max_bytes + 1)
            if len(data) > max_bytes:
                data = data[:max_bytes]
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
                except Exception:
                    pass
            _SSL_MODE, _OPENER = mode, op
            return Result(r.geturl(), r.headers.get("Content-Type", ""), data)
        except urllib.error.HTTPError as e:
            # 404/403 之类是"服务器答了"，也算拿到了（有些站点会带正文）
            try:
                data = e.read(max_bytes)
            except Exception:
                data = b""
            if data:
                _SSL_MODE, _OPENER = mode, _mk_opener(mode)
                return Result(url, e.headers.get("Content-Type", "") if e.headers else "",
                              data)
            last = "HTTP %s" % e.code
            if e.code < 500:
                break
        except ssl.SSLError as e:
            last = "TLS: %s" % e
            continue
        except urllib.error.URLError as e:
            last = str(e.reason)
            if "CERTIFICATE" in str(e.reason).upper() or "SSL" in str(e.reason).upper():
                continue
            break
        except socket.timeout:
            last = "超时"
            break
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            break
    return Result(url, "", b"", last or "抓取失败")


if __name__ == "__main__":
    import sys
    for u in (sys.argv[1:] or ["http://example.com", "https://lite.duckduckgo.com/lite/?q=fpga"]):
        r = fetch(u)
        print("%-60s ok=%s ctype=%s len=%d err=%s"
              % (u[:60], r.ok, r.ctype[:30], len(r.data), r.err))
        if r.ok:
            print("   " + r.text()[:200].replace("\n", " "))
