# Read the fixed platform or implemented checkpoint and collect TIMING-7 evidence.
if {$argc != 2} { error "usage: checkpoint new-output-directory" }
lassign $argv dcp out
if {[file exists $out]} { error "output directory already exists" }
file mkdir $out
set_param general.maxThreads 2
open_checkpoint $dcp

proc one {objects label} {
    if {[llength $objects] != 1} { error "$label expected one object, got [llength $objects]" }
    return [lindex $objects 0]
}

set ref [one [get_clocks io_clk_pcie_00_clk_p] refclk]
set dma [one [get_clocks dma_ip_axi_aclk_1] dma_clock]
report_clock_interaction -file $out/clock_interaction.rpt
foreach direction {forward reverse} from [list $ref $dma] to [list $dma $ref] {
    report_cdc -from $from -to $to -details -all_checks_per_endpoint -no_waiver -file $out/${direction}_cdc.rpt
    foreach delay {min max} {
        report_timing -from $from -to $to -delay_type $delay -max_paths 64 -nworst 1 \
            -no_report_unconstrained -path_type full_clock_expanded -input_pins -file $out/${direction}_${delay}.rpt
        report_timing -from $from -to $to -delay_type $delay -max_paths 64 -nworst 1 \
            -user_ignored -path_type full_clock_expanded -input_pins -file $out/${direction}_${delay}_ignored.rpt
    }
}
# The exceptions report's clock filters would omit scoped pin/cell exceptions.
report_exceptions -coverage -file $out/exceptions_coverage.rpt
report_exceptions -ignored -file $out/exceptions_ignored.rpt
report_exceptions -scope_override -file $out/exceptions_scope_override.rpt
write_xdc $out/effective.xdc

set root level0_i/blp/blp_i/ss_hif/inst/pcie/inst
set reset_name [format {%s/sys_reset_in_async_rst_inst/arststages_ff_reg[1]} $root]
set lut_name $root/debug_wrapper_U/debug_probes_inst_i_1
set reset [one [get_cells -hierarchical -filter [format {NAME == "%s"} $reset_name]] reset_stage]
set lut [one [get_cells -hierarchical -filter [format {NAME == "%s"} $lut_name]] debug_reset_lut]
set reset_q [one [get_pins -of_objects $reset -filter {REF_PIN_NAME == Q}] reset_q]
set lut_q [one [get_pins -of_objects $lut -filter {DIRECTION == OUT}] debug_reset_lut_output]
set topology [open $out/reset_topology.txt {WRONLY CREAT EXCL}]
foreach object [list $ref $dma $reset $lut] {
    puts $topology [report_property -return_string $object]
}
foreach input [get_pins -of_objects $lut -filter {DIRECTION == IN}] {
    puts $topology "LUT input $input nets=[get_nets -of_objects $input]"
    puts $topology "  drivers=[get_pins -leaf -of_objects [get_nets -segments -of_objects $input] -filter {DIRECTION == OUT}]"
    puts $topology "  startpoints=[all_fanin -flat -startpoints_only -trace_arcs all $input]"
}
foreach source [list $reset_q $lut_q] {
    foreach arcs {enabled all} {
        set endpoints [lsort -unique [all_fanout -flat -endpoints_only -trace_arcs $arcs $source]]
        puts $topology "fanout source=$source arcs=$arcs count=[llength $endpoints]"
        foreach endpoint $endpoints {
            set clock_pin {}
            if {[get_property CLASS $endpoint] eq "pin"} {
                set cell [get_cells -of_objects $endpoint]
                if {[llength $cell]} {
                    set clock_pin [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == C}]
                }
            }
            set clocks {}
            if {[llength $clock_pin]} { set clocks [get_clocks -quiet -of_objects $clock_pin] }
            puts $topology "$endpoint clock_pin=$clock_pin clocks=$clocks"
        }
    }
}
set synchronizers [get_cells -hierarchical -filter {IS_PRIMITIVE && NAME =~ */pcie/inst/* &&
    (NAME =~ */sys_reset_in_async_rst_inst/arststages_ff_reg* ||
     NAME =~ */negotiated_width_xpm_cdc_array_single_inst/*ff_reg* ||
     NAME =~ */cur_speed_xpm_cdc_array_single_inst/*ff_reg* ||
     NAME =~ */sys_rst_sbr_cdc_pulse_inst/*ff_reg*)}]
if {![llength $synchronizers]} { error "PCIe CDC stages not found" }
foreach cell [lsort $synchronizers] {
    puts $topology "synchronizer $cell ref=[get_property REF_NAME $cell] ASYNC_REG=[get_property ASYNC_REG $cell]"
}
close $topology
close_design
