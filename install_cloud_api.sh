#!/bin/sh
# install_cloud_api.sh —— 在板子上安装云协同服务
#
# 做四件事：
#   ① 建配置文件和目录
#   ② 装 systemd 服务
#   ③ 起服务并等它监听
#   ④ 自测一遍（HTTP 打几个端点）

set -e

echo "======================================================"
echo " 安装云协同服务"
echo "======================================================"
echo

# ---- ① 配置 ----
echo "【1】配置文件"
if [ -f /etc/xiaobai-cloud.json ]; then
    echo "  已存在，不覆盖：/etc/xiaobai-cloud.json"
    cat /etc/xiaobai-cloud.json
else
    # ★ token 只用 ASCII（HTTP 头只支持 latin-1，中文会直接报错）
    TOKEN=$(head -c 16 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 8)
    cat > /etc/xiaobai-cloud.json <<EOF
{
  "token": "$TOKEN",
  "port": 8768,
  "enable_write": true,
  "discover_port": 8769
}
EOF
    echo "  已生成：/etc/xiaobai-cloud.json"
    echo "  ★ token = $TOKEN"
fi

mkdir -p /var/lib/xiaobai-cloud/uploads
mkdir -p /home/zynq/fpga_jobs
echo "  目录建好了"
echo

# ---- ② 服务 ----
echo "【2】systemd 服务"
if [ -f /home/zynq/cloud-api.service ]; then
    cp /home/zynq/cloud-api.service /etc/systemd/system/cloud-api.service
    systemctl daemon-reload
    systemctl enable cloud-api >/dev/null 2>&1
    echo "  已安装并设为开机自启"
else
    echo "  ★ 找不到 /home/zynq/cloud-api.service"
fi
echo

# ---- ③ 起服务 ----
echo "【3】启动服务"
systemctl restart cloud-api
sleep 4
echo "  状态: $(systemctl is-active cloud-api)"
echo

# ---- ④ 自测 ----
echo "【4】自测"
TOKEN=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['token'])")
PORT=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['port'])")

echo "  --- /health（不需要 token）---"
curl -s --max-time 8 "http://127.0.0.1:$PORT/health" | head -c 200
echo
echo
echo "  --- 不带 token 应该 401 ---"
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://127.0.0.1:$PORT/info")
echo "    HTTP $CODE  $([ "$CODE" = "401" ] && echo '✓' || echo '✗')"
echo
echo "  --- 带 token 拿板子信息 ---"
curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:$PORT/info" | python3 -c "
import json,sys
d = json.load(sys.stdin)
if not d.get('ok'):
    print('    ✗', d.get('error')); raise SystemExit(1)
print('    主机名:', d.get('hostname'))
print('    IP:', d.get('ip'))
print('    温度:', d.get('temperature_c'), '°C')
print('    服务:', ', '.join('%s=%s' % (k,v) for k,v in (d.get('services') or {}).items()))
print('    工具数:', d.get('tools_count'))
b = d.get('bitstream') or {}
if b:
    print('    bitstream:', b.get('size'), '字节  md5', (b.get('md5') or '')[:12])
"
echo
echo "  --- 读 scope_0 的 VERSION ---"
curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:$PORT/hw/regs?base=scope_0&offset=0x34" | head -c 250
echo
echo
echo "  --- 变更历史 ---"
curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:$PORT/hw/changes?limit=3" | head -c 300
echo
echo

echo "======================================================"
echo " 装好了"
echo "======================================================"
IP=$(hostname -I | awk '{print $1}')
echo " 客户端连：http://$IP:$PORT"
echo " token:    $TOKEN"
echo
echo " 局域网发现（UDP $PORT+1）：客户端广播 XIAOBAI_DISCOVER"
echo
echo " 日志：tail -f /var/log/cloud_api.log"
echo " 审计：tail -f /var/lib/xiaobai-cloud/audit.jsonl"
