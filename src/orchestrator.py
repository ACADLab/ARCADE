"""
Orchestrator: end-to-end loop for E1-E4.

Architecture (two rules):
  1. Design Agent gets spec only (no family hint) → generates RTL
  2. Verifier Agent gets spec only (no RTL)       → generates testbench
  3. Golden NMED (fixed C++ harness)               → final math judge

Design and Verifier never share context.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_raem_lock = threading.Lock()  # serialise RAEM store/query across parallel workers

from . import config
from .design_agent import generate as design_generate
from .verifier_agent import generate_testbench as verifier_generate
from .sim_harness import run_verilator, check_nmed_target
from .aptpu_integrator import integrate as aptpu_integrate
from .ppa_loop import run_ppa_flow
from .raem import store as raem_store, query as raem_query, format_context_for_prompt
from .paper_crawler import get_papers_context_for_design

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_FILE = REPO_ROOT / "configs" / "adder_specs.json"
RESULTS_DIR = REPO_ROOT / "results"
WORK_DIR = REPO_ROOT / "work"
FLOW_ROOT = config.OPENROAD_FLOW_DIR
MAX_REPAIR_ITERATIONS = 5


def load_specs() -> list[dict]:
    if not SPECS_FILE.exists():
        return []
    return json.loads(SPECS_FILE.read_text())


def run_verifier_testbench(verilog: str, testbench: str, bit_width: int, spec_id: str = "tmp") -> dict[str, Any]:
    """Run verifier-agent-generated SystemVerilog testbench via Verilator.
    Uses a per-spec working directory so parallel workers don't collide.
    """
    import re as _re2
    import shutil as _shutil
    work = WORK_DIR / f"verifier_{spec_id}"
    work.mkdir(parents=True, exist_ok=True)
    dut_f = work / "approx_adder.v"
    tb_f = work / "tb_verifier.sv"
    obj_dir = work / "obj_dir_verifier"
    # Strip any verilator pragma comments the LLM may have invented (valid or not)
    clean_tb = _re2.sub(r'/\*\s*verilator\b.*?\*/', '', testbench, flags=_re2.IGNORECASE | _re2.DOTALL)
    if obj_dir.exists():
        _shutil.rmtree(obj_dir)
    dut_f.write_text(verilog)
    tb_f.write_text(clean_tb)
    try:
        # Auto-detect top module name from testbench
        import re as _re
        top_module = "tb_verifier"
        m = _re.search(r"^\s*module\s+(\w+)", testbench, _re.MULTILINE)
        if m:
            top_module = m.group(1)
        comp = subprocess.run(
            [
                "verilator", "--binary",
                "--sv", "--no-timing",
                "-Wno-WIDTHEXPAND", "-Wno-WIDTH", "-Wno-WIDTHTRUNC",
                "-Wno-INITIALDLY", "-Wno-SELRANGE", "-Wno-CASEINCOMPLETE",
                "-Wno-UNOPTFLAT", "-Wno-LITENDIAN", "-Wno-MULTIDRIVEN", "-Wno-BADVLTPRAGMA",
                "--top-module", top_module,
                "-o", "sim_verifier",
                "--Mdir", str(obj_dir),
                str(dut_f), str(tb_f),
            ],
            capture_output=True, text=True, timeout=60,
            cwd=str(work),
        )
        if comp.returncode != 0:
            return {"ran": False, "errors": (comp.stderr or comp.stdout or "")[:600]}
        run = subprocess.run(
            [str(obj_dir / "sim_verifier")],
            capture_output=True, text=True, timeout=120,
        )
        stdout = run.stdout or ""
        last_lines = [l.strip().upper() for l in stdout.strip().split("\n") if l.strip()]
        passed = any("PASS" in l for l in last_lines[-3:])
        return {"ran": True, "stdout": stdout[-600:], "passed": passed}
    except FileNotFoundError:
        return {"ran": False, "errors": "verilator not found"}
    except subprocess.TimeoutExpired:
        return {"ran": False, "errors": "verifier testbench timeout"}


def run_spec(
    spec: dict,
    mode: str,
    session_id: str,
    use_raem: bool,
    flow_root: Path | None,
    provider: str = "deepseek",
    no_ppa: bool = False,
) -> dict[str, Any]:
    """
    Run one spec through the full pipeline:
      Design Agent → RTL
      Verifier Agent → testbench (independent, same spec, no RTL)
      Golden NMED → final judge
      PPA → skipped when no_ppa=True (for faster pass@k runs)
    """
    spec_id = spec.get("id", "?")
    nmed_target = spec.get("nmed_target", 0.05)
    bit_width = spec.get("bit_width", 8)

    # RAEM context (E3 only) — uses error signatures, not family names
    raem_context = ""
    if use_raem:
        with _raem_lock:
            past = raem_query(f"bit_width={bit_width} nmed_target={nmed_target}", spec, top_k=3)
        raem_context = format_context_for_prompt(past)

    # Professor/curated papers context for Design Agent (topology and style guidance)
    papers_context = get_papers_context_for_design()

    # Verifier Agent: ONE call, sees only the spec, generates testbench
    verifier_tb, verifier_raw, verifier_meta = verifier_generate(spec, provider=provider)

    repair_feedback = ""
    iterations = 0
    verilog = None
    nmed_result = None
    verifier_result = None

    for it in range(MAX_REPAIR_ITERATIONS):
        if mode == "E1" and it >= 1:
            break
        # E2/E3/E4: up to 5 repair attempts; we break on first pass (no extra runs once target met)
        iterations += 1

        # Design Agent: gets spec + optional papers + RAEM + repair feedback. Never sees testbench.
        verilog, raw, meta = design_generate(
            spec,
            raem_context=raem_context,
            repair_feedback=repair_feedback,
            papers_context=papers_context,
            provider=provider,
        )
        if not verilog:
            if use_raem:
                with _raem_lock:
                    raem_store(
                        session_id=session_id, design_number=None,
                        error_type="generation_failed",
                        error_signature=meta.get("error", raw[:200]),
                        design_context=spec, fix_applied="", success=False, iteration=it,
                    )
            repair_feedback = f"Generation failed: {meta.get('error', raw[:300])}"
            continue

        # Layer 1: Verifier Agent testbench (optional — runs if iverilog available)
        if verifier_tb:
            verifier_result = run_verifier_testbench(verilog, verifier_tb, bit_width, spec_id=spec_id)

        # Layer 2: Golden NMED (fixed C++ harness) — this is the FINAL JUDGE
        nmed_result = run_verilator(verilog, bit_width=bit_width, num_samples=100000 if bit_width > 8 else 0)

        if nmed_result.get("compile_errors"):
            repair_feedback = "Verilator compile errors: " + "; ".join(nmed_result["compile_errors"][:3])
            if use_raem:
                with _raem_lock:
                    raem_store(
                        session_id=session_id, design_number=None,
                        error_type="compile_error", error_signature=repair_feedback,
                        design_context=spec, fix_applied="", success=False, iteration=it,
                    )
            continue

        passed = check_nmed_target(nmed_result, nmed_target)
        if use_raem:
            with _raem_lock:
                raem_store(
                    session_id=session_id, design_number=None,
                    error_type="nmed_fail" if not passed else "nmed_pass",
                    error_signature=f"NMED={nmed_result.get('nmed')} target={nmed_target}",
                    design_context=spec, nmed_after=nmed_result.get("nmed"),
                    success=passed, iteration=it,
                )
        if passed:
            break
        repair_feedback = (
            f"NMED {nmed_result.get('nmed'):.4f} exceeded target {nmed_target}. "
            f"Max abs error: {nmed_result.get('max_abs_error')}. "
            f"Reduce approximation aggressiveness."
        )

    # PPA integration (only if golden NMED passed and PPA not disabled)
    ppa_metrics = {}
    golden_passed = bool(verilog and nmed_result and check_nmed_target(nmed_result, nmed_target))
    ppa_success = None
    ppa_log_tail = None
    run_ppa = golden_passed and not no_ppa and flow_root and flow_root.exists()
    if run_ppa:
        integration = aptpu_integrate(verilog, flow_root=flow_root, dw=bit_width, ww=bit_width, mn=4, mult_dw=8)
        ppa = run_ppa_flow(flow_root=flow_root, timeout_s=1800)
        ppa_metrics = ppa.get("metrics", {})
        ppa_success = ppa.get("success")
        ppa_log_tail = ppa.get("log_lines", [])[-20:]

    out = {
        "spec_id": spec_id,
        "pass": golden_passed,
        "iterations": iterations,
        "nmed": nmed_result.get("nmed") if nmed_result else None,
        "max_abs_error": nmed_result.get("max_abs_error") if nmed_result else None,
        "verifier_agent": {
            "generated": verifier_tb is not None,
            "ran": verifier_result.get("ran", False) if verifier_result else False,
            "passed": verifier_result.get("passed", None) if verifier_result else None,
        },
        "ppa": ppa_metrics,
    }
    if ppa_success is not None:
        out["ppa_success"] = ppa_success
    if ppa_log_tail is not None:
        out["ppa_log_tail"] = ppa_log_tail
    if run_ppa:
        out["integration"] = integration
    return out


def main():
    p = argparse.ArgumentParser(description="APTPU Multi-Agent Orchestrator")
    p.add_argument("--mode", choices=["E1", "E2", "E3", "E4"], default="E1")
    p.add_argument("--limit", type=int, default=1, help="Max specs to run")
    p.add_argument("--spec-id", type=str, help="Run only this spec id (e.g. A1)")
    p.add_argument("--spec-ids", type=str, help="Comma-separated spec ids to run (e.g. A1,A2,A8). Overrides --limit when set (for resume).")
    p.add_argument("--provider", choices=["deepseek", "claude"], default="deepseek")
    p.add_argument("--flow-root", type=str, default="", help="Path to OpenROAD-flow-scripts/flow")
    p.add_argument("--no-ppa", action="store_true",
                   help="Skip PPA (OpenROAD) runs. Use for fast pass@k measurement; run PPA separately afterward.")
    p.add_argument("--workers", type=int, default=1,
                   help="Number of parallel workers for LLM+Verilator phase (PPA always sequential). "
                        "Recommended: 3-4 (DeepSeek rate limit safe). Default: 1.")
    args = p.parse_args()

    specs = load_specs()
    if args.spec_id:
        specs = [s for s in specs if s.get("id") == args.spec_id]
    elif args.spec_ids:
        ids = {s.strip() for s in args.spec_ids.split(",") if s.strip()}
        specs = [s for s in specs if s.get("id") in ids]
        if ids:
            order = {sid: i for i, sid in enumerate(args.spec_ids.split(","))}
            specs.sort(key=lambda s: order.get(s.get("id"), 999))
    if not specs:
        print("No specs found.")
        return
    if not args.spec_ids and not args.spec_id:
        specs = specs[: args.limit]

    flow_root = Path(args.flow_root) if args.flow_root else FLOW_ROOT
    session_id = "run"
    use_raem = args.mode in ("E3", "E4")
    no_ppa = args.no_ppa
    workers = max(1, args.workers)

    print_lock = threading.Lock()

    def _run(spec):
        r = run_spec(
            spec, args.mode, session_id,
            use_raem=use_raem, flow_root=flow_root,
            provider=args.provider, no_ppa=no_ppa,
        )
        with print_lock:
            print(json.dumps(r, indent=2), flush=True)
        return r

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS_DIR / f"{args.mode}_results.json"

    if workers == 1:
        results = [_run(s) for s in specs]
    else:
        # Run LLM+Verilator in parallel; PPA (inside run_spec) is skipped when no_ppa=True.
        # If PPA is enabled and workers>1, warn: PPA is NOT parallel-safe (shared flow dir).
        if not no_ppa and flow_root and (Path(flow_root) / "Makefile").exists():
            print(
                f"[WARNING] --workers {workers} with PPA enabled: PPA runs share the flow "
                "directory and cannot safely overlap. Consider --no-ppa for parallel runs.",
                flush=True,
            )
        results_by_id: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run, s): s.get("id") for s in specs}
            for fut in as_completed(futures):
                r = fut.result()
                results_by_id[r["spec_id"]] = r
        # Restore original spec order
        results = [results_by_id[s["id"]] for s in specs if s["id"] in results_by_id]

    out_file.write_text(json.dumps(results, indent=2))
    print(f"Wrote {out_file}")


if __name__ == "__main__":
    main()
