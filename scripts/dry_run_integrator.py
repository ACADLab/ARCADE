"""Dry run APTPU integrator with stub dir."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.aptpu_integrator import write_adder_rtl, inject_pe_v, set_options_adder_define, add_to_config_mk

stub = Path("work/flow_stub")
stub.mkdir(parents=True, exist_ok=True)
(stub / "designs/src/aptpu").mkdir(parents=True, exist_ok=True)
(stub / "designs/nangate45/aptpu").mkdir(parents=True, exist_ok=True)
(stub / "designs/src/aptpu/pe.v").write_text("// test\n`elsif ACCURATE_ACCUMULATE\n assign x=1;\n`endif\n")
(stub / "designs/nangate45/aptpu/options_definitions.vh").write_text("`define LOA  //APADDER\n")
(stub / "designs/nangate45/aptpu/config.mk").write_text("export VERILOG_FILES = \\\n\t./designs/$(PLATFORM)/$(DESIGN_NICKNAME)/systolic_array_top.v\n")

v = write_adder_rtl("module approx_adder #(parameter A=8,B=4)(input [7:0]a,b, output [8:0]sum); assign sum=a+b; endmodule", stub)
print("write_adder_rtl OK:", v.exists())
print("inject_pe_v OK:", inject_pe_v(stub))
set_options_adder_define(stub)
add_to_config_mk(stub)
print("Integrator dry run passed.")
