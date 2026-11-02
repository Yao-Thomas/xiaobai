#!/bin/sh
# verify_full_loop.sh —— 验证「板子提交 -> PC 执行 -> 结果回到板子」整条闭环
echo "======================================================"
echo " agent 改 FPGA · 完整闭环验证"
echo "======================================================"
echo
echo "【1】板子上的任务目录"
ls -la /home/zynq/fpga_jobs/ 2>/dev/null | tail -5
echo
echo "【2】★ 结果文件内容（这是 PC 侧写回来的）"
RES=$(ls -1 /home/zynq/fpga_jobs/*.result.json 2>/dev/null | tail -1)
if [ -n "$RES" ]; then
  echo "  文件: $RES"
  python3 -c "
import json, sys
d = json.load(open('$RES', encoding='utf-8'))
print('  任务号:   ', d.get('id'))
print('  状态:     ', d.get('status'))
print('  用时:     ', d.get('elapsed_sec'), '秒')
print('  完成时间: ', d.get('ts'))
print('  步骤:')
for s in d.get('steps', []):
    print('    [rc=%s] %s  %.1fs' % (s.get('rc'), s.get('desc'), s.get('elapsed', 0)))
    for ln in (s.get('tail') or '').split(chr(10))[:3]:
        if ln.strip(): print('        ', ln[:100])
if d.get('error'): print('  错误:', d['error'])
"
else
  echo "  ★ 还没有结果文件"
fi
echo
echo "【3】★ 用 agent 的工具查这个任务（agent 视角）"
cd /home/zynq && sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
from agent import tools as T
from agent import hw_tools
r = T.call('hw_fpga_build_status', {}, {})
print(r)
" 2>&1 | head -12
echo
echo "【4】变更单（含这次构建）"
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
from agent import hw_change as HC
for c in HC.change_list(10):
    print('  [%s] %-10s %s' % (c.get('ts'), c.get('kind'), (c.get('detail') or '')[:55]))
" 2>&1
echo
echo "【5】温度"
sudo python3 /home/zynq/thermal_guard.py --once
echo
echo "======================================================"
echo " 闭环：板子 ✓ -> PC 守护 ✓ -> Vivado 执行 ✓ -> 结果回板子 ✓"
echo "======================================================"
