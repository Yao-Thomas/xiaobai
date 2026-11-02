cd /home/zynq/ui || exit 1
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A
from audio_pl import Mem
m = Mem()
print("  常量 I2S_DIV    =", A.I2S_DIV)
print("  常量 MCLK_RATIO =", A.MCLK_RATIO)
print("  常量 FS         =", A.FS)
print("  常量 CHANNELS   =", A.CHANNELS)
print()
print("  实时寄存器（服务在跑）:")
print("    TX I2STIM (0x43C70000+?) =", m.rd(A.I2S_BASE, A.I2S_I2STIM))
print("    RX I2STIM                =", m.rd(A.I2S_RX_BASE, A.I2S_I2STIM))
print("    FMT FS_MULT (0x43C50000+%#x) = %s" % (A.R_FS_MULT, m.rd(A.FMT_BASE, A.R_FS_MULT)))
print("    FMT PERIOD  = 0x%08X" % m.rd(A.FMT_BASE, A.R_PERIOD))
print("    FMT CTRL    = 0x%08X" % m.rd(A.FMT_BASE, A.R_CTRL))
m.close()
PY