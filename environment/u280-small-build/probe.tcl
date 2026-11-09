set_param general.maxThreads 2
if {[catch {
    create_project -in_memory -part xcu280-fsvh2892-2L-e
    add_files -norecurse rtl/VX_afu_axi_limit.sv
    set_property include_dirs [list [file normalize rtl]] [current_fileset]
    set_property verilog_define {SYNTHESIS VIVADO} [current_fileset]
    synth_design -top VX_afu_axi_limit -part xcu280-fsvh2892-2L-e -mode out_of_context
    report_utilization -file post_synth_utilization.rpt
    write_checkpoint post_synth.dcp
    puts "U280_SMALL_SYNTH_PASS"
} message options]} {
    puts stderr "U280_SMALL_SYNTH_FAIL: $message"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
