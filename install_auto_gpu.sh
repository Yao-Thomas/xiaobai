#!/bin/bash
#=====================================================================
#  install_auto_gpu.sh —— 安装"开机自动加载 FPGA GPU"服务
#  以后每次开机: 自动加载 bitstream -> 探测 -> 写标记 -> 桌面用硬件加速
#  探测失败就删标记(桌面安全回退软件渲染, 不会崩溃循环)
#=====================================================================
set -u
echo "=== [1] 安装加载脚本 /usr/local/bin/gpu-load.sh ==="
cat > /usr/local/bin/gpu-load.sh <<'SCRIPT'
#!/bin/bash
# 开机自动加载 FPGA GPU bitstream
# 注意: PL 是易失的, 每次开机都要重新加载; 探测失败必须删标记,
#       否则桌面访问未解码地址会 SIGBUS 崩溃循环
BIN=/lib/firmware/gpu.bin
MARK=/home/zynq/.gpu_addr
BASE=0x43CB0000

log() { echo "[gpu-load] $*"; }

if [ ! -f "$BIN" ]; then
    log "没有 $BIN, 跳过 (桌面用软件渲染)"
    rm -f "$MARK"
    exit 0
fi

log "加载 $BIN ..."
if ! echo gpu.bin > /sys/class/fpga_manager/fpga0/firmware 2>/dev/null; then
    log "写入 firmware 失败, 跳过"
    rm -f "$MARK"
    exit 0
fi
sleep 2

ST=$(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null)
log "FPGA Manager 状态: $ST"
if [ "$ST" != "operating" ]; then
    log "加载失败, 删标记"
    rm -f "$MARK"
    exit 0
fi

# 探测 (放在子进程里: 万一地址未解码触发 SIGBUS, 只死子进程)
if python3 - <<'PYEOF'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from gpu import GPU
    g = GPU(0x43CB0000, verbose=False)
    ok = g.probe()
    g.close()
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PYEOF
then
    echo "0x43CB0000" > "$MARK"
    chown zynq:zynq "$MARK" 2>/dev/null
    log "✅ GPU 存在, 已写标记 (桌面将使用硬件加速)"
else
    rm -f "$MARK"
    log "⚠️ GPU 无响应, 已删标记 (桌面回退软件渲染)"
fi
exit 0
SCRIPT
chmod +x /usr/local/bin/gpu-load.sh
echo "  已安装"

echo ""
echo "=== [2] 安装 systemd 服务 ==="
cat > /etc/systemd/system/zynq-gpu-loader.service <<'UNIT'
[Unit]
Description=Zynq FPGA GPU bitstream loader
# 必须在桌面之前跑完, 这样桌面启动时标记已经就绪
Before=zynq-desktop.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/gpu-load.sh
StandardOutput=append:/var/log/zynq-gpu-load.log
StandardError=append:/var/log/zynq-gpu-load.log

[Install]
WantedBy=multi-user.target
UNIT
echo "  已安装 zynq-gpu-loader.service"

echo ""
echo "=== [3] 让桌面对 loader 有依赖 ==="
mkdir -p /etc/systemd/system/zynq-desktop.service.d
cat > /etc/systemd/system/zynq-desktop.service.d/after-gpu-loader.conf <<'CONF'
[Unit]
After=zynq-gpu-loader.service
Wants=zynq-gpu-loader.service
CONF
echo "  已加 drop-in"

echo ""
echo "=== [4] 启用服务 ==="
systemctl daemon-reload
systemctl enable zynq-gpu-loader.service 2>&1 | tail -2

echo ""
echo "=== [5] 立即测试 loader (不用重启) ==="
systemctl start zynq-gpu-loader.service
sleep 1
echo "  --- loader 日志 ---"
tail -8 /var/log/zynq-gpu-load.log 2>/dev/null | sed 's/^/    /'
echo -n "  标记文件: "; cat /home/zynq/.gpu_addr 2>/dev/null || echo "(无)"

echo ""
echo "=== [6] 重启桌面 (应该自动挂载 GPU) ==="
systemctl restart zynq-desktop
sleep 12
echo -n "  桌面: "; systemctl is-active zynq-desktop
tail -5 /var/log/zynq-desktop.log | sed 's/^/    /'
echo DONE-AUTO
