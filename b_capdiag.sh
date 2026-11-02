cd /home/zynq
which i2cget || echo "  (没有 i2cget)"
sudo python3 cap_diag.py 2>&1