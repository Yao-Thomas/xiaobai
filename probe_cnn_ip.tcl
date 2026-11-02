set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG [open "D:/ubuntu_iso/cnn_ip_probe.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

L "=========== 1. add CNN IP repos ==========="
open_project $PROJ
set cur [get_property ip_repo_paths [current_project]]
set add1 {D:/ubuntu_iso/cnn_hls_2026/work/conv_pool/hls/impl/ip}
set add2 {D:/ubuntu_iso/cnn_hls_2026/work/fc/hls/impl/ip}
foreach a [list $add1 $add2] {
    if {[lsearch $cur $a] < 0} {
        set cur [concat $cur [list $a]]
        L "  adding $a"
    } else { L "  already there: $a" }
}
set_property ip_repo_paths $cur [current_project]
update_ip_catalog -rebuild
L "  ip_repo_paths now: [get_property ip_repo_paths [current_project]]"

L ""
L "=========== 2. find the CNN IP defs ==========="
foreach d [get_ipdefs -quiet *cnn*] { L "  $d" }

L ""
L "=========== 3. interface pins of each CNN IP ==========="
foreach vlnv [list xilinx.com:hls:cnn_conv_pool_q:1.0 xilinx.com:hls:cnn_fc_q:1.0] {
    L ""
    L "--- $vlnv ---"
    if {[llength [get_ipdefs -quiet $vlnv]] == 0} {
        L "  !! IP not found"
        continue
    }
    set ipdef [get_ipdefs $vlnv]
    set vl [get_property VLNV $ipdef]
    L "  VLNV = $vl"
    # 用 create_bd_cell 到临时 BD 太麻烦，直接读 ipdef 的接口
    catch {
        foreach m [get_property -quiet MEMORY_MAPS $ipdef] { }
    }
    # 直接从 IP 的 component.xml 里读端口
    set dir ""
    if {[string match "*conv_pool*" $vlnv]} {
        set dir {D:/ubuntu_iso/cnn_hls_2026/work/conv_pool/hls/impl/ip}
    } else {
        set dir {D:/ubuntu_iso/cnn_hls_2026/work/fc/hls/impl/ip}
    }
    set f [open "$dir/component.xml" r]
    set x [read $f]
    close $f
    # 抓 busInterface 名字
    foreach {m} [regexp -all -inline {<spirit:busInterface>.*?</spirit:busInterface>} $x] {
        if {[regexp {<spirit:name>([^<]+)</spirit:name>} $m -> nm]} {
            if {[regexp {<spirit:busType spirit:name="([^"]+)"} $m -> bt]} {
                L "    iface: $nm  ($bt)"
            } else {
                L "    iface: $nm"
            }
        }
    }
    # 抓端口名
    foreach {m} [regexp -all -inline {<spirit:port>.*?</spirit:port>} $x] {
        if {[regexp {<spirit:name>([^<]+)</spirit:name>} $m -> nm]} { L "    port: $nm" }
    }
}

close $LOG
puts "RESULT=OK"
exit 0