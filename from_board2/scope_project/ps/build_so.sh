#!/bin/sh
# build_so.sh —— 在板上编译 libscopedual.so 并安装
cd /tmp || exit 1
rm -f libscopedual.so
gcc -O2 -fPIC -shared -o libscopedual.so scope_dual.c 2>/tmp/cc.log
RC=$?
echo "gcc exit=$RC"
echo "--- error 行数 ---"
grep -c 'error:' /tmp/cc.log
echo "--- error 明细（最多 8 条）---"
grep 'error:' /tmp/cc.log | head -8
if [ -f libscopedual.so ]; then
    ls -l libscopedual.so
    echo "=== 安装 ==="
    cp /tmp/libscopedual.so /home/zynq/ui/
    rm -rf /home/zynq/ui/__pycache__
    md5sum /home/zynq/ui/libscopedual.so
    echo "SO_INSTALLED"
else
    echo "!! 没有生成 .so"
fi
echo "BUILD_DONE"
