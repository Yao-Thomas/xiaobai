#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xlsxpeek.py —— 只用标准库读 .xlsx (zip + XML), 不需要 openpyxl"""
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def col_idx(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.iter(NS + "sheet")]
    sheets = sorted(n for n in z.namelist()
                    if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    out = []
    for i, sh in enumerate(sheets):
        root = ET.fromstring(z.read(sh))
        rows = []
        for r in root.iter(NS + "row"):
            cells = {}
            for c in r.findall(NS + "c"):
                ref = c.get("r")
                t = c.get("t")
                v = c.find(NS + "v")
                isel = c.find(NS + "is")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr" and isel is not None:
                    val = "".join(x.text or "" for x in isel.iter(NS + "t"))
                elif v is not None:
                    val = v.text
                else:
                    val = ""
                cells[col_idx(ref)] = (val or "").strip()
            if cells:
                w = max(cells) + 1
                rows.append([cells.get(j, "") for j in range(w)])
        out.append((names[i] if i < len(names) else sh, rows))
    return out


if __name__ == "__main__":
    kw = None
    args = [a for a in sys.argv[1:]]
    if "--grep" in args:
        i = args.index("--grep")
        kw = args[i + 1].lower()
        del args[i:i + 2]
    for p in args:
        print("=" * 90)
        print(p)
        print("=" * 90)
        for name, rows in read(p):
            print("--- sheet: %s  (%d 行) ---" % (name, len(rows)))
            n = 0
            for r in rows:
                line = " | ".join(r)
                if kw and kw not in line.lower():
                    continue
                print("   " + line[:230])
                n += 1
                if n > 300:
                    print("   ...")
                    break
        print()
