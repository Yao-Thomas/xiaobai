#!/bin/sh
# verify_deploy_final.sh —— 部署后完整体验证
echo "======================================================"
echo " 部署后验证"
echo "======================================================"
echo

echo "【1】★ 云协同服务"
echo "  服务: $(systemctl is-active cloud-api 2>/dev/null || echo 未装)"
TOKEN=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['token'])" 2>/dev/null)
PORT=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['port'])" 2>/dev/null)
echo "  端口: $PORT   token: $TOKEN"
echo
echo "  --- 本机 127.0.0.1 访问 ---"
curl -s --max-time 8 "http://127.0.0.1:$PORT/health" | head -c 120
echo
echo "  --- ★ 从【局域网 IP】访问（手机走的就是这条路）---"
IP=$(hostname -I | awk '{print $1}')
echo "  板子 IP: $IP"
curl -s --max-time 8 "http://$IP:$PORT/health" | head -c 120
echo
echo "  --- /info 关键字段 ---"
curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" "http://$IP:$PORT/info" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if not d.get('ok'): print('  ✗', d.get('error')); raise SystemExit
print('  主机名:', d.get('hostname'), ' IP:', d.get('ip'))
print('  温度:', d.get('temperature_c'), '°C   守护:', d.get('thermal_level'))
print('  工具数:', d.get('tools_count'))
print('  服务:', ', '.join('%s=%s'%(k,v) for k,v in (d.get('services') or {}).items()))
b=d.get('bitstream') or {}
print('  bitstream:', b.get('size'), '字节  md5', (b.get('md5') or '')[:12])
"
echo

echo "【2】★ 分级推理（规则层，不走模型）"
cd /home/zynq
for q in "现在多少度" "服务状态怎么样" "你是谁"; do
  echo -n "  问「$q」 -> "
  python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
from agent import tiers
t = tiers.Tiers(mode='auto')
m = t.match_rule('$q')
if m: print('规则[%s] 命中' % m['name'])
else: print('没命中（会走模型）')
" 2>&1
done
echo

echo "【3】★ 示波器读取接口（真硬件）"
python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
import scope_capture as SC
r = SC.capture_once(src=0, dec=1, trig_level=128)
if r.get('ok'):
    print('  ✓ 采到 %d 点，采样率 %.0f Hz，触发点 %d' % (len(r['samples']), r['fs_hz'], r['trig_pos']))
    m = r['meta']
    print('    Vpp %s  占空比 %s  估算频率 %s Hz' % (m.get('vpp'), m.get('duty'), m.get('freq_hz')))
    print('    前 12 个样本:', r['samples'][:12])
else:
    print('  ✗', r.get('error'))
" 2>&1
echo

echo "【4】★ 波形 AI 链（示波器 -> STFT -> 28x28）"
python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
import scope_capture as SC, waveform_ai as W
r = SC.capture_once()
if not r.get('ok'):
    print('  ✗ 采集失败:', r.get('error')); raise SystemExit
w = [(v-128)/128.0 for v in r['samples']]
img = W.waveform_to_image(w)
s = W.image_summary(img)
print('  ✓ 28x28 时频图，均值 %.1f，非零 %d/%d' % (s['mean'], s['nonzero'], len(img)))
cls, info = W.classify_with_cnn(img, cnn_script='/home/zynq/cnn_linux.py')
print('  CNN:', ('类别 %s' % cls) if cls is not None else str(info)[:120])
" 2>&1
echo

echo "【5】★ CNN 驱动（真跑一次）"
python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
import cnn_linux
print('  cnn_linux 加载 OK')
" 2>&1 | head -4
sudo python3 /home/zynq/cnn_linux.py --selftest 2>&1 | tail -8 || echo "  (没有 --selftest，跳过)"
echo

echo "【6】★ FPFA 闭环测试（agent 改 FPGA）"
cd /home/zynq && python3 test_fpga_loop.py 2>&1 | grep -E "【|✓|✗|总体" | tail -22
echo

echo "【7】★ 变更历史 App 用的数据"
echo -n "  变更单条数: "
sudo wc -l < /var/lib/hwchange/changes.jsonl 2>/dev/null || echo 0
ls -la /home/zynq/ui/apps_hwchange.py 2>/dev/null | awk '{print "  apps_hwchange.py:", $5, "字节"}'
grep -c "apps_hwchange" /home/zynq/ui/desktop.py 2>/dev/null | awk '{print "  desktop.py 里注册:", $1, "处"}'
echo

echo "【8】★ 现有的核心能力（agent 直接问）"
curl -s --max-time 20 -X POST -H "Content-Type: application/json" \
     -d '{"text":"现在多少度"}' http://127.0.0.1:8765/voice | head -c 200
echo
curl -s --max-time 25 -X POST -H "Content-Type: application/json" \
     -d '{"text":"读一下 scope_0 的寄存器"}' http://127.0.0.1:8765/voice | head -c 300
echo
echo
echo "======================================================"
echo " 完成"
echo "======================================================"
