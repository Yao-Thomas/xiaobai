#!/usr/bin/env bash
# 分别读 fb 的两页，看哪一页在变（判定屏幕到底显示的哪一页）
STRIDE=3072
H=600

read_page() {
  sudo dd if=/dev/fb0 of=$2 bs=$STRIDE count=$H skip=$(( $1 * H )) 2>/dev/null
}

for round in 1 2; do
  echo "=== 第 $round 轮 ==="
  read_page 0 /tmp/p0_$round.raw
  read_page 1 /tmp/p1_$round.raw
  echo "  page0: $(md5sum /tmp/p0_$round.raw | cut -d' ' -f1)  $(stat -c%s /tmp/p0_$round.raw) 字节"
  echo "  page1: $(md5sum /tmp/p1_$round.raw | cut -d' ' -f1)  $(stat -c%s /tmp/p1_$round.raw) 字节"
  if [ "$round" = "1" ]; then sleep 4; fi
done
echo
echo "=== 判断 ==="
p0a=$(md5sum /tmp/p0_1.raw | cut -d' ' -f1); p0b=$(md5sum /tmp/p0_2.raw | cut -d' ' -f1)
p1a=$(md5sum /tmp/p1_1.raw | cut -d' ' -f1); p1b=$(md5sum /tmp/p1_2.raw | cut -d' ' -f1)
[ "$p0a" != "$p0b" ] && echo "  page0 在变 ✓" || echo "  page0 没变"
[ "$p1a" != "$p1b" ] && echo "  page1 在变 ✓" || echo "  page1 没变"
echo
echo "=== 两页内容是否不同 ==="
[ "$p0a" = "$p1a" ] && echo "  两页完全相同（不是双缓冲，或者内容刚好一样）" || echo "  两页内容不同 -> 确实是双缓冲"
echo
echo "=== 把两页都存下来供查看 ==="
cp /tmp/p0_2.raw /tmp/page0.raw
cp /tmp/p1_2.raw /tmp/page1.raw
ls -l /tmp/page0.raw /tmp/page1.raw
