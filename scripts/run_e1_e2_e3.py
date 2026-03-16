#!/usr/bin/env python3
"""
Run E1, E2, and E3 in sequence, then print the LaTeX table for Table I.
Usage:
  python scripts/run_e1_e2_e3.py [--limit N] [--flow-root PATH] [--provider deepseek|claude]
  --limit 3   quick run (default)
  --limit 13  full 13 specs
  --flow-root  optional; if set, integrate + PPA run for passing adders
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description="Run E1, E2, E3 and print LaTeX table")
    ap.add_argument("--limit", type=int, default=3, help="Max specs per mode (default 3)")
    ap.add_argument("--flow-root", type=str, default="", help="OpenROAD flow dir for PPA")
    ap.add_argument("--provider", choices=["deepseek", "claude"], default="deepseek")
    args = ap.parse_args()

    cmd_base = [sys.executable, "-m", "src.orchestrator", "--limit", str(args.limit), "--provider", args.provider]
    if args.flow_root:
        cmd_base.extend(["--flow-root", args.flow_root])

    for mode in ("E1", "E2", "E3"):
        cmd = cmd_base + ["--mode", mode]
        print(f"\n>>> Running: {' '.join(cmd)}\n")
        r = subprocess.run(cmd, cwd=REPO)
        if r.returncode != 0:
            print(f"Warning: {mode} exited with code {r.returncode}")

    # Print LaTeX table
    sys.path.insert(0, str(REPO))
    from src.results_plotter import latex_table_e1_e2_e3
    print("\nLaTeX table (paste into main.tex Table I):\n")
    print(latex_table_e1_e2_e3())
    print()


if __name__ == "__main__":
    main()
