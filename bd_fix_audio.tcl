#=====================================================================
#  bd_fix_audio.tcl -- restore the audio formatter's HP3 DDR segments
#
#  Deleting and re-creating hp3_merge dropped the address assignment for
#  /audio/audio_formatter/m_axi_mm2s and m_axi_s2mm (they used to point at
#  SEG_processing_system7_0_HP3_DDR_LOWOCM).  Without them the BD reports
#  CRITICAL WARNING 41-1356 and audio DMA would go nowhere.
#
#  usage: vivado -mode batch -source bd_fix_audio.tcl
#=====================================================================
set PROJ {D:/ubuntu_iso/atk2026/Navigator_7020/Navigator_7020.xpr}
set LOG  [open "D:/ubuntu_iso/bd_fix_audio_result.txt" w]
proc L {msg} { global LOG; puts $LOG $msg; flush $LOG; puts $msg }

open_project $PROJ
open_bd_design [get_files system.bd]

set SEG [get_bd_addr_segs -quiet */S_AXI_HP3/HP3_DDR_LOWOCM]
L "HP3 DDR segment: $SEG"

foreach aspace {/audio/audio_formatter/m_axi_mm2s /audio/audio_formatter/m_axi_s2mm} {
    if {[catch {
        assign_bd_address -force -offset 0x00000000 -range 1G \
            -target_address_space $aspace $SEG
    } e]} {
        L "  !! $aspace : $e"
    } else {
        L "  OK $aspace -> 0x00000000 / 1G"
    }
}

# also make sure they are not left excluded
foreach aspace {/audio/audio_formatter/m_axi_mm2s /audio/audio_formatter/m_axi_s2mm} {
    foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $aspace]] {
        set ex "?"
        catch {set ex [get_property IS_EXCLUDED $s]}
        set nm "?"
        catch {set nm [get_property NAME $s]}
        L "   $aspace :: $nm excluded=$ex"
    }
}

L ""
L ">>> validate"
set ncrit 0
if {[catch {validate_bd_design} e2]} {
    L " !! validation failed: $e2"
} else {
    L " validated"
}
save_bd_design
generate_target all [get_files system.bd]
L " regenerated"

L ""
L "=== final segments (audio + gpu) ==="
foreach s [lsort [get_bd_addr_segs -quiet]] {
    if {[string match "*audio*" $s] || [string match "*gpu_0*" $s]} {
        set o "?"; catch {set o [get_property offset $s]}
        set r "?"; catch {set r [get_property range $s]}
        L "  $s = $o / $r"
    }
}
close $LOG
puts "RESULT=OK"
exit 0
