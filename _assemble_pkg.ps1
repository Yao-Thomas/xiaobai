# 组装交接包 —— 拷贝文件
$ErrorActionPreference = "SilentlyContinue"
$PKG = "D:\总文件夹\FPGA2026_项目交接包"
$SRC = "D:\总文件夹\FPGA2026"
$U   = "D:\ubuntu_iso"

function mk($p) { New-Item -ItemType Directory -Force -Path $p | Out-Null }

echo "=== 清理旧的 ==="
if (Test-Path $PKG) { Remove-Item $PKG -Recurse -Force }
mk $PKG

# ---------------- 01 板载系统备份 ----------------
mk "$PKG\01_板载系统备份"
Copy-Item "$SRC\系统备份\*" "$PKG\01_板载系统备份\" -Recurse -Force
echo "01 板载系统备份 OK"

# ---------------- 02 FPGA 工程 (排除可再生的构建产物) ----------------
mk "$PKG\02_FPGA工程"
$proj = "$U\atk2026\Navigator_7020"
foreach ($d in @("Navigator_7020.srcs", "Navigator_7020.gen", "ip_repo")) {
    if (Test-Path "$proj\$d") {
        robocopy "$proj\$d" "$PKG\02_FPGA工程\Navigator_7020\$d" /E /NFL /NDL /NJH /NJS /NP | Out-Null
    }
}
Copy-Item "$proj\Navigator_7020.xpr" "$PKG\02_FPGA工程\Navigator_7020\" -Force
if (Test-Path "$proj\system_wrapper.xsa") { Copy-Item "$proj\system_wrapper.xsa" "$PKG\02_FPGA工程\Navigator_7020\" -Force }
# 出流 TCL 脚本
Get-ChildItem "$U" -Filter "*2026*.tcl" | Copy-Item -Destination "$PKG\02_FPGA工程\" -Force
Get-ChildItem "$U" -Filter "*.tcl" | Where-Object { $_.Name -notmatch "2026" } | Copy-Item -Destination "$PKG\02_FPGA工程\" -Force
echo "02 FPGA 工程 OK"

# ---------------- 03 自研 GPU ----------------
mk "$PKG\03_自研GPU\rtl"
mk "$PKG\03_自研GPU\testbench"
mk "$PKG\03_自研GPU\驱动"
mk "$PKG\03_自研GPU\bitstream"
mk "$PKG\03_自研GPU\ip_repo"
Copy-Item "$SRC\fpga_gpu\gpu2d.v","$SRC\fpga_gpu\gpu2d_axi.v" "$PKG\03_自研GPU\rtl\" -Force
Copy-Item "$SRC\fpga_gpu\tb_gpu2d.v","$SRC\fpga_gpu\tb_gpu2d_axi.v" "$PKG\03_自研GPU\testbench\" -Force
Copy-Item "$SRC\fpga_gpu\gpu.py","$SRC\fpga_gpu\gpu_demo.py" "$PKG\03_自研GPU\驱动\" -Force
Copy-Item "$U\ui\gpu.py","$U\ui\gpu_demo.py" "$PKG\03_自研GPU\驱动\" -Force
Copy-Item "$U\gpu_probe.py","$U\gpu_diag.py" "$PKG\03_自研GPU\驱动\" -Force
Copy-Item "$SRC\fpga_gpu\ip_repo\*" "$PKG\03_自研GPU\ip_repo\" -Recurse -Force
Copy-Item "$SRC\fpga_gpu\2018集成\*.tcl" "$PKG\03_自研GPU\" -Force
Copy-Item "$U\atk2026\Navigator_7020\Navigator_7020.runs\impl_1\system_wrapper.bit" "$PKG\03_自研GPU\bitstream\" -Force
Copy-Item "$SRC\fpga_gpu\bit2bin.py" "$PKG\03_自研GPU\" -Force
Copy-Item "$SRC\fpga_gpu\集成指南.md" "$PKG\03_自研GPU\" -Force
echo "03 自研 GPU OK"

# ---------------- 04 板载桌面与应用 ----------------
mk "$PKG\04_板载桌面与应用\ui"
mk "$PKG\04_板载桌面与应用\systemd"
Copy-Item "$U\ui\*.py" "$PKG\04_板载桌面与应用\ui\" -Force
Copy-Item "$U\ui\*.sh" "$PKG\04_板载桌面与应用\ui\" -Force
Copy-Item "$U\mcrender.c" "$PKG\04_板载桌面与应用\ui\" -Force
Copy-Item "$U\ui\shot_board.py" "$PKG\04_板载桌面与应用\ui\" -Force
Copy-Item "$U\run_all_tests.py" "$PKG\04_板载桌面与应用\" -Force
echo "04 桌面与应用 OK"

# ---------------- 05 工具脚本 ----------------
mk "$PKG\05_工具脚本"
Copy-Item "$U\board.py","$U\board10.py","$U\board_verify.py","$U\find_board.py" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\deploy_gpu2026.py","$U\prep_bit2026.py","$U\gpu_probe.py" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\board_serial.py","$U\serial_console.py","$U\serial_sysrq.py","$U\capture_boot.py" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\uboot_now.py","$U\uboot_fpga.py","$U\uboot_test.py","$U\zynqbin.py","$U\zynqbin2.py","$U\dumpboot.py" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\fbbridge.c","$U\minetest_on_board.sh","$U\block_fragment_opt.glsl" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\try_serial.py","$U\try_hosts.py","$U\shot.py","$U\shot_board.py" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\find_fb_phys.py","$U\pl_read.py","$U\disp_swap.py" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\minetest_lowend.conf","$U\xorg_fbdev.conf" "$PKG\05_工具脚本\" -Force
Copy-Item "$U\craft_dl\Craft-master\src\config.h" "$PKG\05_工具脚本\craft_config.h" -Force
echo "05 工具脚本 OK"

# ---------------- 06 文档 ----------------
mk "$PKG\06_文档"
Copy-Item "$SRC\*.md" "$PKG\06_文档\" -Force
Copy-Item "$SRC\交接文档" "$PKG\06_文档\上一轮CNN项目_交接文档" -Recurse -Force
Copy-Item "$SRC\petalinux_系统准备" "$PKG\06_文档\petalinux_系统准备" -Recurse -Force
Copy-Item "$SRC\使用手册.md" "$PKG\06_文档\" -Force
echo "06 文档 OK"

# ---------------- 07 真机截图 ----------------
mk "$PKG\07_真机截图"
Copy-Item "$SRC\真机截图\*" "$PKG\07_真机截图\" -Force
echo "07 真机截图 OK"

# ---------------- 08 界面预览 ----------------
mk "$PKG\08_界面预览"
Copy-Item "$SRC\界面预览\*" "$PKG\08_界面预览\" -Force

# ---------------- 09 上一轮 CNN 项目 ----------------
mk "$PKG\09_上一轮CNN加速器项目"
Copy-Item "$SRC\FPGA2026_ZYNQ_CNN_交接包.zip" "$PKG\09_上一轮CNN加速器项目\" -Force

echo ""
echo "=== 各目录体积 ==="
Get-ChildItem $PKG -Directory | ForEach-Object {
    $b = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
    "{0,-40} {1,8:N1} MB" -f $_.Name, ($b/1MB)
}
$tot = (Get-ChildItem $PKG -Recurse -File | Measure-Object Length -Sum).Sum
"总计: {0:N1} MB" -f ($tot/1MB)
