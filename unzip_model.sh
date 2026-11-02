#!/bin/bash
echo "--- pip 状态 ---"
tail -4 /tmp/pipvosk.log
python3 -c "import vosk; print('VOSK OK')" 2>&1 | tail -1
echo
echo "--- 用 python zipfile 解压模型（不依赖 unzip）---"
if [ -d /home/zynq/vosk-model-small-cn-0.22 ]; then
  echo "已存在"
else
  python3 - <<'PY'
import zipfile, os
src = "/tmp/cn.zip"
dst = "/home/zynq"
with zipfile.ZipFile(src) as z:
    names = z.namelist()
    print("  压缩包内条目:", len(names), " 顶层:", sorted({n.split('/')[0] for n in names}))
    z.extractall(dst)
print("  解压完成")
PY
fi
echo
echo "--- 结果 ---"
ls -d /home/zynq/vosk-model* 2>&1
du -sh /home/zynq/vosk-model* 2>/dev/null
ls /home/zynq/vosk-model-small-cn-0.22 2>/dev/null | head -10
