"""
PPA Loop: run OpenROAD flow via Docker (openroad/orfs) or native make (orfs-build).
Parse area/power/WNS from reports.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import config as _config
REPO_ROOT = _config.REPO_ROOT
# Native orfs build: set OPENROAD_NATIVE_FLOW env to your flow directory
ORFS_BUILD_FLOW = Path(os.environ.get("OPENROAD_NATIVE_FLOW", "")).resolve() if os.environ.get("OPENROAD_NATIVE_FLOW") else None
if ORFS_BUILD_FLOW and not ORFS_BUILD_FLOW.exists():
    ORFS_BUILD_FLOW = None
RESULTS_BASE = "results/nangate45/aptpu/base"
LOGS_BASE = "logs/nangate45/aptpu/base"
REPORTS_BASE = "reports/nangate45/aptpu/base"
OBJECTS_BASE = "objects/nangate45/aptpu/base"
DESIGN_CONFIG = "DESIGN_CONFIG=./designs/nangate45/aptpu/config.mk"


def clear_aptpu_flow_artifacts(flow_root: Path) -> None:
    """
    Remove logs, results, reports, and objects for the aptpu design so make
    runs a full flow for the current RTL instead of reusing previous run state.
    Call before each PPA run when the design may have changed.
    """
    flow_root = flow_root.resolve()
    for sub in (LOGS_BASE, RESULTS_BASE, REPORTS_BASE, OBJECTS_BASE):
        d = flow_root / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def run_openroad_native(flow_root: Path, timeout_s: int = 3600) -> tuple[bool, list[str]]:
    """Run OpenROAD flow with native make (orfs-build). flow_root must contain Makefile."""
    flow_root = flow_root.resolve()
    if not flow_root.exists():
        return False, [f"Flow directory does not exist: {flow_root}"]
    makefile = flow_root / "Makefile"
    if not makefile.exists():
        return False, [f"No Makefile in {flow_root}"]
    clear_aptpu_flow_artifacts(flow_root)
    designs_src = flow_root / "designs"
    if designs_src.exists():
        opt_def = designs_src / "nangate45" / "aptpu" / "options_definitions.vh"
        src_aptpu = designs_src / "src" / "aptpu"
        if opt_def.exists() and src_aptpu.exists():
            shutil.copy2(opt_def, src_aptpu / "options_definitions.vh")
    cmd = ["make", DESIGN_CONFIG]
    try:
        out = subprocess.run(
            cmd,
            cwd=str(flow_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        lines = (out.stdout or "").split("\n") + (out.stderr or "").split("\n")
        return out.returncode == 0, lines
    except FileNotFoundError:
        return False, ["make not found or not in PATH"]
    except subprocess.TimeoutExpired:
        return False, ["OpenROAD flow timed out"]


def run_openroad_docker(flow_root: Path, timeout_s: int = 3600) -> tuple[bool, list[str]]:
    """
    Run OpenROAD flow inside Docker. flow_root must be absolute and contain
    flow/designs/ (with nangate45/aptpu and src/aptpu). We mount only designs/
    into the image so the image's Makefile, platforms, scripts are used.
    Returns (success, list of stdout lines).
    """
    flow_root = flow_root.resolve()
    if not flow_root.exists():
        return False, [f"Flow directory does not exist: {flow_root}"]
    designs_src = flow_root / "designs"
    if not designs_src.exists():
        return False, [f"Flow designs directory does not exist: {designs_src}"]
    clear_aptpu_flow_artifacts(flow_root)
    # RTL in designs/src/aptpu/ use `include "options_definitions.vh"`; file lives in nangate45/aptpu
    opt_def = designs_src / "nangate45" / "aptpu" / "options_definitions.vh"
    src_aptpu = designs_src / "src" / "aptpu"
    if opt_def.exists() and src_aptpu.exists():
        shutil.copy2(opt_def, src_aptpu / "options_definitions.vh")
    # So we can read results/logs/reports after the run, create and mount them on the host
    for sub in ("results", "logs", "reports"):
        (flow_root / sub).mkdir(parents=True, exist_ok=True)
    # Mount designs + results/logs/reports so container writes where we can read
    cmd = [
        "docker", "run", "--rm",
        "--platform", "linux/amd64",  # image has no arm64; required on Apple Silicon
        "-v", f"{designs_src}:/OpenROAD-flow-scripts/flow/designs",
        "-v", f"{flow_root / 'results'}:/OpenROAD-flow-scripts/flow/results",
        "-v", f"{flow_root / 'logs'}:/OpenROAD-flow-scripts/flow/logs",
        "-v", f"{flow_root / 'reports'}:/OpenROAD-flow-scripts/flow/reports",
        "-w", "/OpenROAD-flow-scripts/flow",
        "openroad/orfs:latest",
        "make", DESIGN_CONFIG,
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        lines = (out.stdout or "").split("\n") + (out.stderr or "").split("\n")
        return out.returncode == 0, lines
    except FileNotFoundError:
        return False, ["docker not found or not in PATH"]
    except subprocess.TimeoutExpired:
        return False, ["OpenROAD flow timed out"]


def extract_metrics_from_reports(flow_root: Path) -> dict[str, Any]:
    """Parse area, utilization, WNS, TNS, power from OpenROAD reports.
    Falls back to 3_* logs when 6_* are missing (e.g. flow failed at CTS on ARM emulation).
    """
    metrics: dict[str, Any] = {}
    flow_root = flow_root.resolve()
    log_file = flow_root / LOGS_BASE / "6_report.log"
    if log_file.exists():
        content = log_file.read_text()
        m = re.search(r"Design area\s+([\d.]+)\s+u", content)
        if m:
            metrics["area_um2"] = float(m.group(1))
        m = re.search(r"(\d+)%\s+utilization", content)
        if m:
            metrics["utilization_percent"] = int(m.group(1))
    # Fallback: after place/resize we have area in 3_* logs (e.g. when CTS fails on emulation)
    if "area_um2" not in metrics:
        for log_name in ("3_5_place_dp.log", "3_4_place_resized.log", "3_3_place_gp.log", "2_1_floorplan.log"):
            p = flow_root / LOGS_BASE / log_name
            if p.exists():
                m = re.search(r"Design area\s+([\d.]+)\s+u", p.read_text())
                if m:
                    metrics["area_um2"] = float(m.group(1))
                    metrics["from_partial_run"] = True
                    break

    for timing_file in [
        flow_root / REPORTS_BASE / "6_finish.rpt",
        flow_root / RESULTS_BASE / "6_final.rpt",
        flow_root / LOGS_BASE / "6_finish.log",
    ]:
        if not timing_file.exists():
            continue
        content = timing_file.read_text()
        if "wns_ns" not in metrics:
            m = re.search(r"^wns\s+([-\d.]+)\s*$", content, re.MULTILINE | re.IGNORECASE)
            if m:
                try:
                    metrics["wns_ns"] = float(m.group(1))
                except ValueError:
                    pass
        if "tns_ns" not in metrics:
            m = re.search(r"^tns\s+([-\d.]+)\s*$", content, re.MULTILINE | re.IGNORECASE)
            if m:
                try:
                    metrics["tns_ns"] = float(m.group(1))
                except ValueError:
                    pass
        if "worst_slack_ns" not in metrics:
            m = re.search(r"^worst slack\s+([-\d.]+)\s*$", content, re.MULTILINE | re.IGNORECASE)
            if m:
                try:
                    metrics["worst_slack_ns"] = float(m.group(1))
                except ValueError:
                    pass
        if metrics.get("wns_ns") is not None:
            break

    for power_file in [
        flow_root / REPORTS_BASE / "6_finish.rpt",
        flow_root / RESULTS_BASE / "6_final_power.rpt",
        flow_root / REPORTS_BASE / "6_final_power.rpt",
    ]:
        if not power_file.exists():
            continue
        content = power_file.read_text()
        m = re.search(
            r"Total\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+100\.0%",
            content,
        )
        if m:
            metrics["power_internal_w"] = float(m.group(1))
            metrics["power_switching_w"] = float(m.group(2))
            metrics["power_leakage_w"] = float(m.group(3))
            metrics["power_total_w"] = float(m.group(4))
            break

    gdsii = flow_root / RESULTS_BASE / "6_final.gds"
    metrics["gdsii_generated"] = gdsii.exists()
    if gdsii.exists():
        metrics["gdsii_size_mb"] = round(gdsii.stat().st_size / (1024 * 1024), 2)
    return metrics


def run_ppa_flow(flow_root: Path | None = None, timeout_s: int = 3600, use_native: bool | None = None) -> dict[str, Any]:
    """
    Run OpenROAD flow and return metrics. flow_root defaults to OPENROAD_NATIVE_FLOW or orfs-build/flow if present, else OpenROAD-flow-scripts/flow.
    When flow_root contains a Makefile (e.g. native orfs-build), runs make natively; otherwise uses Docker.
    use_native=True forces native; use_native=False forces Docker; use_native=None auto-detect from Makefile.
    On failure, still tries to extract area from partial 3_* logs.
    """
    flow_root = (flow_root or ORFS_BUILD_FLOW or FLOW_ROOT_DEFAULT).resolve()
    if use_native is None:
        use_native = (flow_root / "Makefile").exists()
    if use_native:
        success, log_lines = run_openroad_native(flow_root, timeout_s=timeout_s)
    else:
        success, log_lines = run_openroad_docker(flow_root, timeout_s=timeout_s)
    result = {"success": success, "log_lines": log_lines[-50:]}
    result["metrics"] = extract_metrics_from_reports(flow_root)
    return result


if __name__ == "__main__":
    r = run_ppa_flow()
    print("Success:", r["success"])
    print("Metrics:", r.get("metrics"))
