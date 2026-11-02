echo "########## 1) agent 环境变量（模型 + key）##########"
sudo cat /etc/zynq-agent.env 2>/dev/null | sed -E 's/(KEY|key|TOKEN|token)=.{6}.*/\1=***已隐藏***/'
echo
echo "########## 2) config.py 里的默认模型 ##########"
grep -nE "model|MODEL|deepseek|base_url|api|url" /home/zynq/agent/config.py | head -25
echo
echo "########## 3) llm.py 里的模型定义 ##########"
grep -nE "model|MODEL|deepseek|url|api_key|def " /home/zynq/agent/llm.py | head -25
echo
echo "########## 4) core.py 里的 SYSTEM 提示词开头 ##########"
sed -n '28,45p' /home/zynq/agent/core.py
echo
echo "########## 5) 运行时实际用的模型（问 agent 自己）##########"
curl -s --max-time 8 http://127.0.0.1:8765/health 2>/dev/null | head -c 400
echo