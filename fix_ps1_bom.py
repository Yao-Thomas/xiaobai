import os, glob

ROOT = r"D:\总文件夹\FPGA2026"
BOM = b"\xef\xbb\xbf"

for p in glob.glob(os.path.join(ROOT, "*.ps1")):
    raw = open(p, "rb").read()
    if raw.startswith(BOM):
        print("  %s : 已有 BOM ✅" % os.path.basename(p))
        continue
    # 按 UTF-8 解码, 再带 BOM 写回
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        print("  %s : 不是 UTF-8, 跳过" % os.path.basename(p))
        continue
    with open(p, "wb") as f:
        f.write(BOM + txt.encode("utf-8"))
    print("  %s : 已加 BOM ✅ (%d 字节)" % (os.path.basename(p), len(BOM) + len(txt.encode('utf-8'))))

print("")
print("=== 逐个做语法检查 ===")
import subprocess
ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
for p in sorted(glob.glob(os.path.join(ROOT, "*.ps1"))):
    cmd = ("$e=$null; "
           "[void][System.Management.Automation.PSParser]::Tokenize("
           "(Get-Content -Raw -LiteralPath '%s'), [ref]$e); "
           "if($e.Count -eq 0){'OK'}else{'ERR: ' + $e[0].Message}" % p)
    r = subprocess.run([ps, "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    out = (r.stdout or "").strip()
    print("  %-22s %s" % (os.path.basename(p), out))
