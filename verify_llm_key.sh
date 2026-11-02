#!/bin/sh
# verify_llm_key.sh —— 在板子上验证 /llm/key（包括 Linux 的 600 权限）
#
# ══════════════════════════════════════════════════════════════════
# ★★★ 这个脚本最早的清理逻辑把【真 key】删了 —— 记下来 ★★★
# ══════════════════════════════════════════════════════════════════
# 当时的清理是：
#     out = [l for l in lines if not l.strip().startswith("DEEPSEEK_API_KEY=")]
# 想法是"删掉刚写的测试 key"，但那行就是 agent 真正在用的 key ——
# 删完之后 agent 就报"没有配置 API key"。是从 deploy_agent.py 里
# 找到原 key 才恢复的。
#
# ⇒ 现在这个脚本【第一步就备份】，还原时是"把备份里那行原样加回去"，
#   不是"删掉那一行"。
# ══════════════════════════════════════════════════════════════════
ENVF=/etc/zynq-agent.env
BAK=/etc/zynq-agent.env.bak_llmkey_test

echo "======================================================"
echo " /llm/key 端点验证"
echo "======================================================"
echo

echo "=== ① ★ 先备份真实配置（这一步不能省）==="
sudo cp -f $ENVF $BAK
sudo chmod 600 $BAK
if sudo grep -q "^DEEPSEEK_API_KEY=" $BAK; then
    echo "   ✓ 备份里含 DEEPSEEK_API_KEY"
    ORIG_KEY=$(sudo grep "^DEEPSEEK_API_KEY=" $BAK | head -1)
else
    echo "   ⚠ 备份里【没有】DEEPSEEK_API_KEY"
    ORIG_KEY=""
fi
echo "   备份: $BAK"
echo

echo "=== 重启 cloud-api（带上新端点）==="
sudo systemctl restart cloud-api
sleep 5
echo "  cloud-api: $(systemctl is-active cloud-api)"
echo
echo "=== 板上跑离线测试（这次会验 600 权限）==="
cd /home/zynq && python3 test_llm_key.py 2>&1 | tail -18
echo
echo "=== 真机测：写一个假 key，确认 600 + 不回显 ==="
TOKEN=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['token'])" 2>/dev/null)
echo "  --- 写之前 env 文件 ---"
sudo ls -la /etc/zynq-agent.env 2>/dev/null | awk '{print "    "$1, $3, $4, $5, $9}'
echo
echo "  --- 写一个测试 key ---"
curl -s --max-time 15 -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"key":"sk-TESTONLY-0123456789abcdefghij"}' \
  http://127.0.0.1:8768/llm/key | head -c 300
echo
echo
echo "  --- 写之后 ---"
sudo ls -la /etc/zynq-agent.env 2>/dev/null | awk '{print "    权限="$1, "属主="$3":"$4, "大小="$5}'
echo -n "    key 行数: "
sudo grep -c "DEEPSEEK_API_KEY" /etc/zynq-agent.env 2>/dev/null
echo
echo "  --- /llm/config 看看（应该 has_key=true，但看不到 key 本身）---"
curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8768/llm/config | head -c 200
echo
echo
echo "  --- 审计里有没有泄露完整 key ---"
sudo tail -3 /var/lib/xiaobai-cloud/audit.jsonl 2>/dev/null
echo -n "    审计里有完整 key 吗: "
if sudo grep -q "sk-TESTONLY-0123456789abcdefghij" /var/lib/xiaobai-cloud/audit.jsonl 2>/dev/null; then
  echo "★ 有！泄露了"
else
  echo "✓ 没有（只有前 4 位）"
fi
echo
echo "=== ★★★ 从备份还原（不是删掉那一行！）==="
if [ -n "$ORIG_KEY" ]; then
    sudo sh -c "grep -v '^DEEPSEEK_API_KEY=' $ENVF > /tmp/_env_r"
    sudo sh -c "echo '$ORIG_KEY' >> /tmp/_env_r"
    sudo sh -c "mv -f /tmp/_env_r $ENVF"
    sudo chmod 600 $ENVF
    sudo chown root:root $ENVF
    echo "   ✓ 已从备份把原始 key 行【原样】加回去"
else
    echo "   （备份里本来就没有 key，跳过还原）"
fi
sudo sed 's/\(=.\{8\}\).*/\1****/' $ENVF | sed 's/^/    /'
echo
sudo systemctl restart zynq-agent
sleep 6
echo "  zynq-agent: $(systemctl is-active zynq-agent)"
PID=$(systemctl show zynq-agent -p MainPID --value 2>/dev/null)
echo "  环境里 DEEPSEEK 出现次数: $(sudo tr '\0' '\n' < /proc/$PID/environ 2>/dev/null | grep -c DEEPSEEK)"
echo
echo "=== 温度 ==="
sudo python3 /home/zynq/thermal_guard.py --once
