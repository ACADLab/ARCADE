#!/usr/bin/env python3
"""
Run E1, E2, E3 on all 13 specs (A1--A13), then print LaTeX for Table I and optionally patch main.tex.
Usage:
  cd aptpu_agents && source .venv/bin/activate
  python scripts/run_all_experiments_and_update_paper.py [--skip-run] [--update-tex]

  --skip-run   Only regenerate table from existing E1/E2/E3 results.
  --update-tex Write Table I into VTS_special_session_march_4/main.tex (replaces placeholder rows).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAPER_DIR = REPO.parent / "VTS_special_session_march_4"
RESULTS_DIR = REPO / "results"


def run_mode(mode: str, limit: int = 13) -> bool:
    cmd = [sys.executable, "-m", "src.orchestrator", "--mode", mode, "--limit", str(limit)]
    r = subprocess.run(cmd, cwd=REPO)
    return r.returncode == 0


def load(mode: str) -> list[dict]:
    p = RESULTS_DIR / f"{mode}_results.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())


def table_row(name: str, data: list[dict]) -> str:
    n = len(data) or 1
    pass1 = sum(1 for r in data if r.get("pass")) / n * 100
    iters = sum(r.get("iterations", 0) for r in data) / n
    nmeds = [r.get("nmed") for r in data if r.get("nmed") is not None]
    avg_nmed = (sum(nmeds) / len(nmeds) * 100) if nmeds else 0.0
    return f"{name} & {pass1:.0f}\\% & {iters:.1f} & {avg_nmed:.3f}\\\\\n"


def latex_table() -> str:
    e1, e2, e3 = load("E1"), load("E2"), load("E3")
    s = "\\begin{tabular}{lccc}\n\\hline\nExperiment & Pass@1 (\\%) & Avg.\\ iter. & Avg.\\ NMED (\\%)\\\\\n\\hline\n"
    s += table_row("E1 (baseline)", e1)
    s += table_row("E2 (closed loop)", e2)
    s += table_row("E3 (with RAEM)", e3)
    s += "\\hline\n\\end{tabular}"
    return s


def update_paper_tex():
    main_tex = PAPER_DIR / "main.tex"
    if not main_tex.exists():
        print("Paper not found:", main_tex)
        return
    text = main_tex.read_text()
    # Replace the three data rows in Table I
    old = """E1 (baseline)     & -- & 1.0 & -- \\
E2 (closed loop) & -- & -- & -- \\
E3 (with RAEM)   & -- & -- & -- \\"""
    tbl = latex_table()
    new_lines = [ln for ln in tbl.split("\n") if ln.strip().startswith("E1 ") or ln.strip().startswith("E2 ") or ln.strip().startswith("E3 ")]
    new = "\n".join(new_lines)
    if old not in text:
        print("Could not find placeholder table block in main.tex")
        return
    text = text.replace(old, new)
    main_tex.write_text(text)
    print("Updated", main_tex)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-run", action="store_true", help="Only regenerate table from existing results")
    ap.add_argument("--update-tex", action="store_true", help="Write Table I into main.tex")
    args = ap.parse_args()

    if not args.skip_run:
        print("Running E1 (13 specs)...")
        run_mode("E1", 13)
        print("Running E2 (13 specs)...")
        run_mode("E2", 13)
        print("Running E3 (13 specs)...")
        run_mode("E3", 13)

    print("\nLaTeX table (Table I):\n")
    print(latex_table())
    print()

    if args.update_tex:
        update_paper_tex()


if __name__ == "__main__":
    main()
