import os
ROOT = r"D:\总文件夹\FPGA2026"
p = os.path.join(ROOT, "全自动出流.ps1")
raw = open(p, "rb").read()
BOM = b"\xef\xbb\xbf"
if not raw.startswith(BOM):
    txt = raw.decode("utf-8")
    with open(p, "wb") as f:
        f.write(BOM + txt.encode("utf-8"))
    print("  已加 BOM: %s" % os.path.basename(p))
else:
    print("  已有 BOM: %s" % os.path.basename(p))

# 语法检查
import subprocess
ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
cmd = ("$e=$null; [void][System.Management.Automation.PSParser]::Tokenize("
       "(Get-Content -Raw -LiteralPath '%s'), [ref]$e); "
       "if($e.Count -eq 0){'语法 OK'}else{'语法错误: ' + $e[0].Message}" % p)
r = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=120)
print("  " + (r.stdout or "").strip())
