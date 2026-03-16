"""
Verilator-based verification harness: compile approx_adder.v, run C++ testbench,
compute NMED (golden reference = exact addition). Returns nmed, pass/fail, and error metrics.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = REPO_ROOT / "harness"
WORK_DIR = REPO_ROOT / "work"
OBJ_DIR = HARNESS_DIR / "obj_dir"


def run_verilator(verilog_content: str, bit_width: int = 8, num_samples: int = 0) -> dict[str, Any]:
    """
    Write verilog to work/approx_adder.v, run Verilator + tb_adder.cpp, parse NMED from stdout.
    bit_width: ADDER_LENGTH. num_samples: 0 = exhaustive for 8-bit, else random count.
    Returns dict with nmed, pass (bool), compile_errors, max_abs_error, raw_stdout, etc.
    """
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    v_file = WORK_DIR / "approx_adder.v"
    v_file.write_text(verilog_content)

    # Verilator compile
    cmd_build = [
        "verilator",
        "--cc",
        "--exe",
        "-o", "sim",
        "-Wno-WIDTHEXPAND",
        "-Wno-WIDTH",
        "-Wno-WIDTHTRUNC",
        str(v_file),
        str(HARNESS_DIR / "tb_adder.cpp"),
    ]
    try:
        out_build = subprocess.run(
            cmd_build,
            cwd=str(HARNESS_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return {
            "nmed": None,
            "pass": False,
            "compile_errors": ["verilator not found in PATH"],
            "max_abs_error": None,
            "raw_stdout": "",
            "raw_stderr": "",
        }
    except subprocess.TimeoutExpired:
        return {
            "nmed": None,
            "pass": False,
            "compile_errors": ["Verilator compile timeout"],
            "max_abs_error": None,
            "raw_stdout": "",
            "raw_stderr": "",
        }

    if out_build.returncode != 0:
        return {
            "nmed": None,
            "pass": False,
            "compile_errors": (out_build.stderr or out_build.stdout or "").split("\n"),
            "max_abs_error": None,
            "raw_stdout": out_build.stdout or "",
            "raw_stderr": out_build.stderr or "",
        }

    # make -C obj_dir -f Vapprox_adder.mk
    make_cmd = ["make", "-C", "obj_dir", "-f", "Vapprox_adder.mk"]
    out_make = subprocess.run(
        make_cmd,
        cwd=str(HARNESS_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if out_make.returncode != 0:
        return {
            "nmed": None,
            "pass": False,
            "compile_errors": (out_make.stderr or out_make.stdout or "").split("\n"),
            "max_abs_error": None,
            "raw_stdout": out_make.stdout or "",
            "raw_stderr": out_make.stderr or "",
        }

    # Run sim: ./obj_dir/sim <ADDER_LENGTH> [num_samples]  (Verilator -o sim)
    run_cmd = [str(HARNESS_DIR / "obj_dir" / "sim"), str(bit_width)]
    if num_samples > 0:
        run_cmd.append(str(num_samples))
    try:
        out_run = subprocess.run(
            run_cmd,
            cwd=str(HARNESS_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "nmed": None,
            "pass": False,
            "compile_errors": [],
            "max_abs_error": None,
            "raw_stdout": "",
            "raw_stderr": "Simulation timeout",
        }

    stdout = out_run.stdout or ""
    stderr = out_run.stderr or ""
    # Parse: NMED=0.012 MED_avg=... max_abs_err=... count=... ADDER_LENGTH=...
    nmed = None
    max_abs_err = None
    m = re.search(r"NMED=([\d.e+-]+)\s+MED_avg=([\d.e+-]+)\s+max_abs_err=(\d+)", stdout)
    if m:
        nmed = float(m.group(1))
        max_abs_err = int(m.group(3))

    return {
        "nmed": nmed,
        "pass": nmed is not None and out_run.returncode == 0,
        "compile_errors": [] if out_run.returncode == 0 else (stderr or stdout).split("\n"),
        "max_abs_error": max_abs_err,
        "raw_stdout": stdout,
        "raw_stderr": stderr,
        "returncode": out_run.returncode,
    }


def check_nmed_target(result: dict[str, Any], nmed_target: float) -> bool:
    """True if result passed and nmed <= nmed_target."""
    if not result.get("pass") or result.get("nmed") is None:
        return False
    return result["nmed"] <= nmed_target


if __name__ == "__main__":
    # Minimal 8-bit adder (exact) for smoke test
    minimal_v = """
module approx_adder #(
    parameter ADDER_LENGTH   = 8,
    parameter IMPRECISE_PART = 4
) (
    input  wire [ADDER_LENGTH-1:0] a,
    input  wire [ADDER_LENGTH-1:0] b,
    output wire [ADDER_LENGTH:0]   sum
);
    assign sum = a + b;
endmodule
"""
    r = run_verilator(minimal_v, bit_width=8, num_samples=0)
    print("NMED:", r.get("nmed"), "pass:", r.get("pass"), "max_abs_error:", r.get("max_abs_error"))
    if r.get("compile_errors"):
        print("Errors:", r["compile_errors"][:5])
