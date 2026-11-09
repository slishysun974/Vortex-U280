# Read existing checkpoints only. No timing exceptions, waivers, or implementation edits.
if {$argc != 2} { error "usage: checkpoint output-directory" }
set dcp [lindex $argv 0]
set out [lindex $argv 1]
file mkdir $out
set_param general.maxThreads 2
open_checkpoint $dcp
report_methodology -name readiness -file $out/methodology.rpt
report_clocks -file $out/clocks.rpt
check_timing -verbose -override_defaults {no_input_delay no_output_delay unconstrained_internal_endpoints} -file $out/check_timing.rpt
write_xdc -force $out/effective.xdc
set details [open $out/objects.txt w]
set errors [open $out/optional_errors.txt w]
proc capture {label script} {
    global details errors
    puts $details "\n=== $label ==="
    if {[catch {uplevel 1 $script} value options]} {
        puts $errors "${label}: $value"
        puts $details "ERROR: $value"
    } else { puts $details $value }
    flush $details
}
foreach v [get_methodology_violations -name readiness] {
    set name [get_property NAME $v]
    if {[regexp {^TIMING-(1|7|14|54)#} $name]} {
        capture "violation $name" {report_property -return_string $v}
        foreach kind {cells pins nets clocks ports} {
            capture "$name related $kind" {
                set objects [get_$kind -quiet -of_objects $v]
                set count [llength $objects]
                set sample [lrange $objects 0 63]
                set props "object_count=$count\nfirst_64_objects=$sample\n"
                if {$count > 64} { puts $errors "$name related ${kind}: property detail limited to 64 of $count objects" }
                foreach obj $sample { append props [report_property -return_string $obj] "\n" }
                set props
            }
        }
    }
}
foreach c [get_clocks] {
    capture "clock [get_property NAME $c]" {report_property -return_string $c}
}
set c1 [get_clocks -quiet io_clk_pcie_00_clk_p]
set c2 [get_clocks -quiet dma_ip_axi_aclk_1]
if {[llength $c1] == 1 && [llength $c2] == 1} {
    capture timing7_forward {report_timing -from $c1 -to $c2 -max_paths 10 -path_type full_clock_expanded -file $out/timing7_forward.rpt}
    capture timing7_reverse {report_timing -from $c2 -to $c1 -max_paths 10 -path_type full_clock_expanded -file $out/timing7_reverse.rpt}
} else { puts $errors "TIMING-7 expected clock pair absent" }
capture clock_interaction {report_clock_interaction -file $out/clock_interaction.rpt}
capture timing_summary {report_timing_summary -report_unconstrained -max_paths 5 -file $out/timing_summary.rpt}
set lut [get_cells -quiet {level0_i/blp/blp_i/ss_cmp/inst/mgmt_debug_bridge/inst/bsip/inst/USE_SOFTBSCAN.U_BSCAN_TAP/U_BASETAP/update_INST_0}]
if {[llength $lut] == 1} {
    capture timing14_lut {report_property -return_string $lut}
    capture timing14_fanout {
        set pins [get_pins -of_objects $lut -filter {DIRECTION == OUT}]
        set endpoints [all_fanout -flat -endpoints_only -from $pins]
        set listing "count=[llength $endpoints]\n"
        foreach ep $endpoints { append listing "$ep\n" }
        set listing
    }
} else { puts $errors "TIMING-14 expected LUT absent" }
close $details
close $errors
close_design
