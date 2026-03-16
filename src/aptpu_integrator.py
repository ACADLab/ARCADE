"""
APTPU Integrator: insert a new LLM-generated adder into the APTPU flow.
- Writes adder Verilog to flow/designs/src/aptpu/
- Injects `elsif LLM_APPROX_ADDER` block in pe.v before ACCURATE_ACCUMULATE
- Sets options_definitions.vh to `define LLM_APPROX_ADDER  //APADDER
- Appends llm_approx_adder.v to config.mk VERILOG_FILES
Expects flow directory already populated with the APTPU design (RTL + config.mk).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import config as _config
REPO_ROOT = _config.REPO_ROOT
FLOW_SRC_APTPU = "designs/src/aptpu"
FLOW_DESIGN_APTPU = "designs/nangate45/aptpu"
ADDER_FILE_NAME = "llm_approx_adder.v"
ADDER_DEFINE = "LLM_APPROX_ADDER"


def _flow_dirs(flow_root: Path) -> tuple[Path, Path]:
    src = flow_root / FLOW_SRC_APTPU
    design = flow_root / FLOW_DESIGN_APTPU
    return src, design


def write_adder_rtl(verilog_content: str, flow_root: Path) -> Path:
    """Write adder Verilog to flow/designs/src/aptpu/llm_approx_adder.v."""
    src, _ = _flow_dirs(flow_root)
    src.mkdir(parents=True, exist_ok=True)
    out = src / ADDER_FILE_NAME
    out.write_text(verilog_content)
    return out


def inject_pe_v(flow_root: Path) -> bool:
    """
    If pe.v exists, inject `elsif LLM_APPROX_ADDER` block before `elsif ACCURATE_ACCUMULATE`.
    Instantiation: approx_adder #(.ADDER_LENGTH(OUTWIDTH),.IMPRECISE_PART(IMPRECISE_PART)) llm_approx_adder_inst (.a(mult_product),.b(pe_result),.sum(pe_accum));
    Returns True if injection was done or already present.
    """
    src, _ = _flow_dirs(flow_root)
    pe_v = src / "pe.v"
    if not pe_v.exists():
        return False
    content = pe_v.read_text()
    if "LLM_APPROX_ADDER" in content:
        return True
    # Insert before "`elsif ACCURATE_ACCUMULATE" the new block
    block = (
        "`elsif LLM_APPROX_ADDER\n"
        " approx_adder #(.ADDER_LENGTH(OUTWIDTH),.IMPRECISE_PART(IMPRECISE_PART)) llm_approx_adder_inst (.a(mult_product),.b(pe_result),.sum(pe_accum));\n\n"
    )
    pattern = r"(\s*)(`elsif ACCURATE_ACCUMULATE\s)"
    m = re.search(pattern, content)
    if not m:
        return False
    new_content = content[: m.start()] + block + m.group(1) + m.group(2) + content[m.end() :]
    pe_v.write_text(new_content)
    return True


def set_options_adder_define(flow_root: Path, adder_define: str = ADDER_DEFINE) -> bool:
    """Set options_definitions.vh to use the given adder define (e.g. LLM_APPROX_ADDER)."""
    _, design = _flow_dirs(flow_root)
    vh = design / "options_definitions.vh"
    if not vh.exists():
        return False
    content = vh.read_text()
    # Replace the line that ends with //APADDER
    content = re.sub(r"`define \w+\s+//APADDER", f"`define {adder_define}  //APADDER", content)
    vh.write_text(content)
    return True


def add_to_config_mk(flow_root: Path, filename: str = ADDER_FILE_NAME) -> bool:
    """Append filename to VERILOG_FILES in config.mk (before systolic_array_top.v)."""
    _, design = _flow_dirs(flow_root)
    config_mk = design / "config.mk"
    if not config_mk.exists():
        return False
    content = config_mk.read_text()
    if filename in content:
        return True
    # Insert before the line that contains systolic_array_top.v (after Zero_Mux.v \)
    line = f"    ./designs/src/$(DESIGN_NICKNAME)/{filename} \\\n"
    pattern = r"(\t\./designs/\$\(PLATFORM\)/\$\(DESIGN_NICKNAME\)/systolic_array_top\.v)"
    m = re.search(pattern, content)
    if not m:
        return False
    content = content[: m.start()] + line + m.group(1) + content[m.end() :]
    config_mk.write_text(content)
    return True


def integrate(
    verilog_content: str,
    flow_root: Path | None = None,
    *,
    dw: int = 8,
    ww: int = 8,
    mn: int = 4,
    mult_dw: int = 8,
) -> dict[str, Any]:
    """
    Full integration: write RTL, inject pe.v, set options_definitions.vh, update config.mk.
    Optionally set DW, WW, M, N, MULT_DW in options_definitions.vh (same regex as tpu_gen_gdsii).
    """
    flow_root = flow_root or FLOW_ROOT_DEFAULT
    results = {"written": False, "pe_injected": False, "options_set": False, "config_updated": False}

    src, design = _flow_dirs(flow_root)
    if not src.exists():
        results["error"] = f"Flow src dir does not exist: {src}"
        return results

    write_adder_rtl(verilog_content, flow_root)
    results["written"] = True

    results["pe_injected"] = inject_pe_v(flow_root)

    # Set adder define and optionally DW, WW, M, N, MULT_DW
    vh = design / "options_definitions.vh"
    if vh.exists():
        content = vh.read_text()
        content = re.sub(r"`define \w+\s+//APADDER", f"`define {ADDER_DEFINE}  //APADDER", content)
        content = re.sub(r"`define DW \d+", f"`define DW {dw}", content)
        content = re.sub(r"`define WW \d+", f"`define WW {ww}", content)
        content = re.sub(r"`define M \d+", f"`define M {mn}", content)
        content = re.sub(r"`define N \d+", f"`define N {mn}", content)
        content = re.sub(r"`define MULT_DW \d+", f"`define MULT_DW {mult_dw}", content)
        vh.write_text(content)
        results["options_set"] = True

    results["config_updated"] = add_to_config_mk(flow_root)
    return results


if __name__ == "__main__":
    # Smoke test: just check paths and that we can call integrate (will fail if flow not set up)
    r = integrate("module approx_adder #(parameter ADDER_LENGTH=8, parameter IMPRECISE_PART=4)(input [7:0] a,b, output [8:0] sum); assign sum=a+b; endmodule", flow_root=REPO_ROOT / "work" / "flow_stub")
    print("Integrate result (stub):", r)
