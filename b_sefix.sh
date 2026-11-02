cd /home/zynq/ui
TS=$(date +%Y%m%d_%H%M%S)
sudo cp webfetch.py webfetch.py.bak_search_$TS
echo "  已备份: webfetch.py.bak_search_$TS"
sudo cp /tmp/wf_new.py webfetch.py
sudo chown zynq:zynq webfetch.py
md5sum webfetch.py
python3 -c "import ast,io; ast.parse(io.open('webfetch.py',encoding='utf-8').read()); print('syntax OK')"
echo
echo "=== 验证: norm_url 现在指向哪 ==="
python3 - <<'PYEOF'
import sys
sys.path.insert(0, '/home/zynq/ui')
import importlib, webfetch as W
importlib.reload(W)
print("  SEARCH =", W.SEARCH)
for u in ("zynq 教程", "现在", "https://example.com", "example.com", "fpga"):
    print("  %-22s -> %s" % (u, W.norm_url(u)))
print()
print("  实测抓一次中文搜索:")
r = W.fetch(W.norm_url("现在"), timeout=15, max_bytes=200*1024)
print("    ok=%s ctype=%s bytes=%d" % (r.ok, r.ctype, len(r.data)))
if r.ok:
    print("    前120字:", r.text()[:120].replace("\n"," "))
PYEOF