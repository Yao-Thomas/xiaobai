hostname -I
echo -n "  服务: "; for s in zynq-desktop zynq-audio zynq-agent; do printf "%s=%s " "$s" "$(systemctl is-active $s)"; done; echo