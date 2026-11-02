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
