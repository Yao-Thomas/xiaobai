#!/bin/bash
# minetest_on_board.sh —— 在 Zynq 板子上跑 Minetest (纯软件渲染)
#
# 原理:
#   Ubuntu 的 Minetest 用 Irrlicht 的 X11 后端, 非要一个真 X server;
#   而这块板子的 X (fbdev/modesetting) 起不来。所以:
#       Xvfb (虚拟X, 低分辨率)  ->  Minetest 在上面渲染 (llvmpipe 软件 GL)
#            |  实时帧缓冲文件 /tmp/Xvfb_screen0 (XWD, 32bpp)
#            v
#       fbbridge (自写的小程序, 最近邻放大)  ->  /dev/fb0 (真实 LCD 1024x600)
#
# 用法:
#   sudo ./minetest_on_board.sh start [宽 高 视距]   # 默认 512 300 20
#   sudo ./minetest_on_board.sh stop                # 停掉并恢复桌面
#   sudo ./minetest_on_board.sh status
#
# 实测性能 (Zynq-7020, 双核 A9 @667MHz):
#   1024x600 视距40  -> FPS 1,  drawtime 695ms
#    512x300 视距20  -> FPS 1,  drawtime 601ms
#   结论: 瓶颈在顶点/几何处理, 降分辨率作用有限。能跑, 但不可玩。

set -u
BR=/home/zynq
FB_W=1024; FB_H=600

mk_conf() {
    local W=$1 H=$2 VR=$3
    for H2 in /home/zynq/.minetest /root/.minetest; do
        mkdir -p $H2
        cat > $H2/minetest.conf <<EOF
screenW = $W
screenH = $H
fullscreen = true
fps_max = 60
fps_max_unfocused = 60
vsync = false
viewing_range = $VR
active_block_range = 1
max_block_generate_distance = 3
max_block_send_distance = 3
enable_shaders = false
enable_3d_clouds = false
smooth_lighting = false
leaves_style = simple
opaque_water = true
enable_waving_plants = false
enable_waving_leaves = false
enable_dynamic_shadows = false
enable_fog = false
enable_sound = false
sound_volume = 0
creative_mode = true
enable_damage = false
mip_map = false
bilinear_filter = false
trilinear_filter = false
anisotropic_filter = 1
menu_clouds = false
serverlist_url =
EOF
    done
}

do_stop() {
    pkill -9 -f "/usr/games/minetest" 2>/dev/null
    pkill -9 -f "Xvfb :1"            2>/dev/null
    pkill -9 -f "fbbridge"           2>/dev/null
    sleep 2
    rm -f $BR/.guard_pause
    systemctl start zynq-desktop
    sleep 6
    echo "已停止。桌面: $(systemctl is-active zynq-desktop)"
}

case "${1:-start}" in
start)
    W=${2:-512}; H=${3:-300}; VR=${4:-20}
    echo "== 停止桌面 + 暂停看门狗 =="
    systemctl stop zynq-desktop
    touch $BR/.guard_pause
    pkill -9 -f "/usr/games/minetest" 2>/dev/null
    pkill -9 -f "Xvfb :1" 2>/dev/null
    pkill -9 -f fbbridge 2>/dev/null
    sleep 2

    echo "== 编译桥接 (如果没有) =="
    [ -x $BR/fbbridge ] || gcc -O2 -w -o $BR/fbbridge $BR/fbbridge.c

    echo "== 起 Xvfb ${W}x${H} =="
    rm -f /tmp/Xvfb_screen0
    setsid nohup Xvfb :1 -screen 0 ${W}x${H}x24 -fbdir /tmp -nolisten tcp \
        > $BR/xvfb_run.log 2>&1 &
    sleep 5
    DISPLAY=:1 timeout 8 xdpyinfo >/dev/null 2>&1 || { echo "Xvfb 起不来"; do_stop; exit 1; }

    echo "== 起桥接 (${W}x${H} -> ${FB_W}x${FB_H}) =="
    setsid nohup $BR/fbbridge -v -r 30 > $BR/bridge_run.log 2>&1 &
    sleep 2

    echo "== 起 Minetest (视距 $VR) =="
    mk_conf $W $H $VR
    export HOME=/home/zynq DISPLAY=:1
    export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe ALSOFT_DRIVERS=null
    cd $BR
    setsid nohup /usr/games/minetest \
        --config /home/zynq/.minetest/minetest.conf \
        --world /home/zynq/.minetest/worlds/w1 \
        --go --name zynq > $BR/mt_run.log 2>&1 &
    echo "  minetest pid=$!"
    echo
    echo "跑起来了。用 ./minetest_on_board.sh stop 停止并恢复桌面。"
    ;;
stop)   do_stop ;;
status)
    echo "minetest : $(pgrep -f '/usr/games/minetest' | head -1)"
    echo "Xvfb     : $(pgrep -f 'Xvfb :1' | head -1)"
    echo "fbbridge : $(pgrep -f fbbridge | head -1)"
    echo "desktop  : $(systemctl is-active zynq-desktop)"
    ;;
*)  sed -n '2,25p' "$0" ;;
esac
