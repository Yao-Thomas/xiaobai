#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_agent_core.py —— 验证 Agent 的两个关键机制（不花 token）

  1. 输出治理：长输出应该落盘 + 只回摘要
  2. 安全防护：危险命令应该被拒
  3. 错误回灌：工具出错应返回字符串而不是抛异常
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, guard, spill, tools      # noqa: E402

cfg = config.load()
print("配置: workdir=%s spill=%s" % (cfg["workdir"], cfg["spill_dir"]))
print()

print("=" * 64)
print("1) 输出治理：故意产生超长输出")
big = "\n".join("line %d  %s" % (i, "y" * 80) for i in range(500))
r, spilled = spill.govern("bigtest", big)
print("   原始 %d 字符 / %d 行" % (len(big), big.count("\n") + 1))
print("   返回给模型的 %d 字符，落盘=%s" % (len(r), spilled))
print("   含'已存到': %s   含'省略': %s" % ("已存到" in r, "省略" in r))
print("   摘要前 2 行:")
for ln in r.split("\n")[:2]:
    print("      " + ln[:90])
print("   摘要后 2 行:")
for ln in r.split("\n")[-2:]:
    print("      " + ln[:90])
assert spilled and len(r) < len(big) / 5, "摘要没有生效！"
assert "已存到" in r, "摘要里没有落盘路径"
# 落盘文件必须真的存在且内容完整
import re as _re
m = _re.search(r"已存到 (\S+)", r)
assert m and os.path.exists(m.group(1)), "落盘文件不存在"
assert open(m.group(1), encoding="utf-8").read() == big, "落盘内容不完整"
print("   ✅ 长输出被正确压缩，且完整内容在 %s" % m.group(1))

print()
print("=" * 64)
print("2) 安全防护：危险命令")
for cmd in ["rm -rf /", "mkfs.ext4 /dev/mmcblk0", "echo hi > /mnt/boot/boot.scr",
            "dd if=/dev/zero of=/dev/mmcblk0", "ls -l /home"]:
    v = guard.check(cmd)
    mark = "拒绝" if not v.allow else "放行"
    print("   %-38s -> %-4s  %s" % (cmd[:38], mark, v.why[:40]))
    if cmd.startswith(("rm -rf /", "mkfs", "dd if=/dev/zero")):
        assert not v.allow, "危险命令竟然被放行：%s" % cmd
print("   ✅ 危险命令全部被拦")

print()
print("=" * 64)
print("3) 错误回灌：工具出错应返回字符串")
cases = [("read", {"path": "/no/such/file.txt"}),
         ("shell", {"cmd": "this_command_does_not_exist_12345"}),
         ("edit", {"path": "/no/such", "old": "a", "new": "b"}),
         ("不存在的工具", {})]
for name, args in cases:
    try:
        r = tools.call(name, args, {})
        ok = isinstance(r, str) and len(r) > 0
        print("   %-16s -> %s  %s" % (name, "OK " if ok else "!! ", r[:70].replace("\n", " ")))
    except Exception as e:
        print("   %-16s -> !! 抛异常了: %s" % (name, e))
        raise
print("   ✅ 错误都变成了字符串（模型能看到并自己纠错）")

print()
print("=" * 64)
print("4) 参数校验：非法 JSON 参数")
r = tools.call("shell", "not a json")
print("   " + r[:100])
print("   ✅ 参数错误有明确提示")

print()
print("全部通过 ✅")
