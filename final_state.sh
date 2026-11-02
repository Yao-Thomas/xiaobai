echo -n "  zynq-agent  : "; systemctl is-active zynq-agent
echo -n "  zynq-audio  : "; systemctl is-active zynq-audio
echo -n "  静音锁      : "; [ -f /etc/zynq-silent ] && echo 存在 || echo 无
echo -n "  音频单元    : "; [ -f /etc/systemd/system/zynq-audio.service ] && echo 在原位 || echo 已移走(封锁)