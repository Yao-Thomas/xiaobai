#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
echo "=== 安装 PIL ==="
apt-get install -y --no-install-recommends python3-pil 2>&1 | tail -4
echo ""
echo "=== 验证 PIL ==="
python3 - <<'EOF'
import PIL
from PIL import Image, ImageDraw, ImageFont, ImageChops
print("PIL 版本:", PIL.__version__)
im = Image.new("RGB", (100, 50), (20, 30, 60))
d = ImageDraw.Draw(im)
d.rectangle([5, 5, 90, 40], fill=(60, 120, 200))
print("绘图测试 OK, 模式:", im.mode)
# 测试 24bpp BGR 输出
raw = im.convert("BGR;24").tobytes()
print("BGR;24 输出字节数:", len(raw), "(应为 100*50*3 =", 100*50*3, ")")
EOF
echo ""
echo "=== 可用字体 ==="
fc-list 2>/dev/null | head -6
echo "--- ttf 目录 ---"
find /usr/share/fonts -name "*.ttf" 2>/dev/null | head -10
find /usr/share/fonts -name "*.ttc" 2>/dev/null | head -5
echo PIL_DONE
