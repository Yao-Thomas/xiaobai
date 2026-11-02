#=====================================================================
#  test_ip_propagate.tcl —— 快速验证：改了 IP 源码，怎么让它传播到 .gen
#
#  ★ 为什么写这个：
#    改 gpu_ip/src/gpu2d_axi.v 后直接出流，发现 .gen/ipshared 里
#    那份【没更新】⇒ 综合用的还是旧代码，白跑 25 分钟。
#    这个脚本只做 update_ip_catalog + generate_target（不综合），
#    1-2 分钟就能知道改动传没传过去。
#
#  跑完看 build_ip_test_result.txt 里的 md5 / default 分支。
#=====================================================================

set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/build_ip_test_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

set GEN {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.gen/sources_1/bd/system/ipshared/eaea/src/gpu2d_axi.v}
set SRC {D:/ubuntu_iso/gpu_ip/src/gpu2d_axi.v}

proc show_default {tag path} {
    global LOG
    if {[file exists $path]} {
        set fp [open $path r]; set t [read $fp]; close $fp
        foreach line [split $t "\n"] {
            if {[string match "*default: s_axi_rdata*" $line]} {
                L "  $tag: [string trim $line]"
            }
        }
    } else {
        L "  $tag: (文件不存在)"
    }
}

L "======================================================"
L " IP 传播测试"
L "======================================================"
L ""
L "--- 跑之前 ---"
show_default "源(gpu_ip)"   $SRC
show_default "gen(ipshared)" $GEN

open_project $PROJ
L " project opened"

L ""
L ">>> update_ip_catalog -rebuild"
update_ip_catalog -rebuild

L ">>> generate_target all"
if {[catch {generate_target all [get_files system.bd]} e]} {
    L " generate_target 出错: $e"
} else {
    L " OK"
}

L ""
L "--- 跑之后 ---"
show_default "源(gpu_ip)"   $SRC
show_default "gen(ipshared)" $GEN

# 也把 IP 的状态打出来
L ""
L "=== 工程里的 IP 状态 ==="
foreach ip [get_ips -quiet] {
    if {[string match "*gpu*" $ip]} {
        L "  $ip  status=[get_property IP_STATUS $ip]"
    }
}

L ""
L "=== end ==="
close $LOG
exit 0
