# -*- coding: utf-8 -*-
"""查清 desktop.py / fbui.py / apps_scope_dual.py 的真实编码与行尾"""
import os

FILES = [
    r"D:\ubuntu_iso\handover\board_ui\desktop.py",
    r"D:\ubuntu_iso\handover\board_ui\fbui.py",
    r"D:\ubuntu_iso\from_board2\scope_project\ps\apps_scope_dual.py",
    r"D:\ubuntu_iso\from_board2\scope_project\ps\scope_dual.py",
]
for p in FILES:
    raw = open(p, "rb").read()
    print("=" * 70)
    print(os.path.basename(p), "  %d bytes" % len(raw))
    print("  BOM?            ", raw[:3] == b"\xef\xbb\xbf")
    print("  CRLF count      ", raw.count(b"\r\n"), " lone-CR:", raw.count(b"\r") - raw.count(b"\r\n"))
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            s = raw.decode(enc)
            print("  decode %-8s OK   chars=%d  re-encode==bytes? %s"
                  % (enc, len(s), s.encode(enc) == raw))
        except Exception as e:
            print("  decode %-8s FAIL %s" % (enc, str(e)[:70]))
