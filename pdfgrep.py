#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdfgrep.py —— 从原理图 PDF 里抽文字并按关键词找网络/连接器

用法: python pdfgrep.py <pdf> <关键词1> [关键词2 ...]
     python pdfgrep.py <pdf> --dump      # 全部文字
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import fitz          # PyMuPDF
    HAVE = "fitz"
except Exception:
    fitz = None
    HAVE = None
    try:
        import pypdf
        HAVE = "pypdf"
    except Exception:
        HAVE = None


def pages_text(path):
    out = []
    if HAVE == "fitz":
        doc = fitz.open(path)
        for i, pg in enumerate(doc):
            out.append((i + 1, pg.get_text("text")))
        doc.close()
    elif HAVE == "pypdf":
        import pypdf
        r = pypdf.PdfReader(path)
        for i, pg in enumerate(r.pages):
            out.append((i + 1, pg.extract_text() or ""))
    else:
        raise SystemExit("没有可用的 PDF 库")
    return out


def main():
    path = sys.argv[1]
    args = sys.argv[2:]
    if not args:
        raise SystemExit(__doc__)
    pts = pages_text(path)
    print("=" * 84)
    print(" %s   (%d 页, 用 %s)" % (path.split("\\")[-1], len(pts), HAVE))
    print("=" * 84)

    if args == ["--dump"]:
        for n, t in pts:
            print("\n########## 第 %d 页 ##########" % n)
            print(t)
        return

    for kw in args:
        print()
        print("### 关键词: %s" % kw)
        hits = 0
        for n, t in pts:
            for line in t.splitlines():
                if kw.lower() in line.lower():
                    print("   [p%-3d] %s" % (n, line.strip()[:150]))
                    hits += 1
                    if hits > 60:
                        print("   ...")
                        return
        if hits == 0:
            print("   (无)")


if __name__ == "__main__":
    main()
