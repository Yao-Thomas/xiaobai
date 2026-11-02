echo "=== 我是谁 ==="
hostname; hostname -I; uptime; date
echo
echo "=== 服务 ==="
for s in zynq-desktop zynq-audio zynq-agent; do printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"; done
echo
echo "=== 网络 ==="
ip -4 addr show wlx688fc92bd646 | grep inet