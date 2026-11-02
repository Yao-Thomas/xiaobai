#=====================================================================
#  check_ip2018.tcl —— 看 2018.3 里有哪些视频 IP 版本
#  (get_ipdefs 需要先有打开的工程)
#=====================================================================
set NEW {D:/ubuntu_iso/tmp_try2018/ipcheck}
if {[file exists $NEW]} { file delete -force $NEW }
create_project -force ipcheck $NEW -part xc7z020clg400-2

puts "======================================================"
puts " Vivado [version -short] 可用的视频 IP"
puts "======================================================"

foreach pat {*v_tc* *v_frmbuf* *v_tpg* *v_axi4s_vid_out* *v_vid_in_axi4s*} {
    set ips [get_ipdefs -all $pat]
    puts ""
    puts "--- $pat : [llength $ips]"
    foreach i [lsort $ips] {
        puts "    [get_property VLNV $i]"
    }
}
exit 0
