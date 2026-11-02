# -*- coding: utf-8 -*-
"""离线验证 deploy_ps.py 的两个文本变换（不碰板子）"""
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HB = os.path.dirname(HERE)
sys.path.insert(0, HB)
import deploy_ps as D  # noqa: E402

print("### 1) build_patched_scope_dual('0x43CF0000') ###")
p = D.build_patched_scope_dual("0x43CF0000")
txt = open(p, encoding="utf-8").read()
for ln in txt.splitlines():
    if "DEFAULT_BASE" in ln or ln.strip().startswith("MARKER"):
        print("   " + ln.strip())
assert "DEFAULT_BASE = 0x43CF0000" in txt, "DEFAULT_BASE 没改对"
assert 'MARKER = "/home/zynq/.scope_dual_addr"' in txt, "MARKER 没改对"
assert "/home/zynq/.scope_addr\"" not in txt, "还残留旧 MARKER"
print("   OK: DEFAULT_BASE + MARKER 都改对了，旧 .scope_addr 已不残留")

print()
print("### 2) patch_desktop_text() on the real baseline desktop.py ###")
src = r"D:\ubuntu_iso\handover\board_ui\desktop.py"
txt, nl = D.read_text_exact(src)
import hashlib as _h
print("   原文件 %d B  md5=%s  (行尾=%s)"
      % (os.path.getsize(src), _h.md5(open(src, 'rb').read()).hexdigest(),
         "CRLF" if nl == "\r\n" else "LF"))
new = D.patch_desktop_text(txt, nl)
out = os.path.join(HB, "_stage", "desktop_patched_TEST.py")
os.makedirs(os.path.dirname(out), exist_ok=True)
D.write_text_exact(out, new)
print("   补丁后 %d B（%d -> %d 字节）" % (os.path.getsize(out), os.path.getsize(src),
                                          os.path.getsize(out)))
bm = set(re.findall(r'"mod":\s*"([A-Za-z0-9_]+)"', txt))
nm = set(re.findall(r'"mod":\s*"([A-Za-z0-9_]+)"', new))
print("   APPS mod 条目: %d -> %d" % (len(bm), len(nm)))
print("   新增 = %s" % sorted(nm - bm))
print("   丢失 = %s" % sorted(bm - nm))
assert nm - bm == {"apps_scope_dual"}, "新增条目不对"
assert not (bm - nm), "弄丢了原有条目"
print("   OK: 只多出 apps_scope_dual，原有 %d 条一条没丢" % len(bm))
print("   icon_scope_dual 出现 %d 次 ; apps_scope_dual 出现 %d 次"
      % (new.count("icon_scope_dual"), new.count("apps_scope_dual")))

print()
print("### 2b) 强断言①：原文件每一行都原样在（只允许插入） ###")
a = txt.splitlines()
b = new.splitlines()
j = 0
inserted = 0
ok = True
for ln2 in a:
    while j < len(b) and b[j] != ln2:
        j += 1
        inserted += 1
    if j >= len(b):
        print("   ★ FAIL 找不到原行: %r" % ln2[:80])
        ok = False
        break
    j += 1
inserted += len(b) - j
print("   原有 %d 行  ->  补丁后 %d 行；插入 %d 行；原有行是否全在: %s"
      % (len(a), len(b), inserted, ok))
assert ok, "补丁改动了原有内容"

print()
print("### 2c) 强断言②：CRLF 行尾保持 ###")
print("   CRLF: %d -> %d" % (txt.count("\r\n"), new.count("\r\n")))
assert new.count("\r\n") >= txt.count("\r\n"), "CRLF 丢了"

print()
print("### 3) py_compile the patched desktop.py ###")
r = subprocess.run([sys.executable, "-m", "py_compile", out], capture_output=True)
print("   py_compile rc=%d" % r.returncode)
if r.returncode:
    print(r.stderr.decode()[-2000:])
assert r.returncode == 0, "补丁后语法不过"

print()
print("### 4) 插入位置确认 ###")
for i, ln in enumerate(new.splitlines()):
    if "apps_scope_dual" in ln and "mod" in ln:
        print("   L%d: %s" % (i + 1, ln.strip()))
    if ln.startswith("def icon_scope_dual"):
        print("   L%d: %s" % (i + 1, ln.strip()))
        print("        (后面跟着 class Desktop? -> %s)"
              % ("是" if any(x.startswith("class Desktop") for x in new.splitlines()[i:i + 30]) else "否"))

print()
print("### 5) 幂等保护：再打一次应当报错 ###")
try:
    D.patch_desktop_text(new)
    print("   ★ 没报错 —— 幂等保护失效！")
    sys.exit(1)
except D.Fail as e:
    print("   OK: 重复打补丁被拒绝 -> %s" % e)

print()
print("ALL_TRANSFORM_TESTS_PASS")
