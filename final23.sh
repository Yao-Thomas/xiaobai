echo -n "  zynq-agent : "; systemctl is-active zynq-agent
echo -n "  zynq-audio : "; systemctl is-active zynq-audio
echo -n "  静音锁     : "; [ -f /etc/zynq-silent ] && echo 生效
sudo bash /tmp/codec_reset.sh --check 2>/dev/null | head -6