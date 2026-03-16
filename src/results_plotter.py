"""
Generate matplotlib figures and LaTeX table snippets from experiment results (E1-E4).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
FIGURES_DIR = REPO_ROOT.parent.parent / "VTS_special_session_march_4" / "figures"


def load_results(mode: str) -> list[dict]:
    p = RESULTS_DIR / f"{mode}_results.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _estimate_pass_at_k(num_samples: int, num_correct: int, k: int) -> float:
    """
    Unbiased pass@k estimator:
        pass@k = 1 - C(n-c, k) / C(n, k)
    where n = num_samples, c = num_correct.

    This is the standard estimator from the HumanEval / code-gen literature.
    Returns nan if n < k (not enough samples to estimate).
    Returns 1.0 if n - c < k (impossible to pick k all-wrong).
    """
    import math
    n, c = num_samples, num_correct
    if n < k:
        return float("nan")
    if n - c < k:
        return 1.0
    # C(n-c, k) / C(n, k) = product_{i=0}^{k-1} (n-c-i)/(n-i)
    # Compute in log-space for numerical stability with large n/k
    log_ratio = sum(
        math.log(n - c - i) - math.log(n - i) for i in range(k)
    )
    return 1.0 - math.exp(log_ratio)


def compute_pass_at_k(results: list[dict], k: int) -> float:
    """
    Compute the mean unbiased pass@k estimate across all specs.

    For each spec:
      n = number of iterations run (attempts made)
      c = 1 if the spec passed, 0 otherwise

    Since E2/E3 break at the first pass, n = iterations and c in {0,1}.
    """
    estimates = []
    for r in results:
        n = r.get("iterations", 1)
        c = 1 if r.get("pass") else 0
        est = _estimate_pass_at_k(n, c, k)
        if not (est != est):  # skip nan
            estimates.append(est)
    if not estimates:
        return float("nan")
    return sum(estimates) / len(estimates)


def summary_table(modes: list[str] | None = None) -> dict:
    """
    Return a dict of per-mode summary stats for printing or table generation.
    Includes: n_specs, pass@1, pass@3, pass@5, avg_iterations, avg_nmed, gdsii_rate.
    """
    if modes is None:
        modes = ["E1", "E2", "E3", "E4"]
    rows = {}
    for mode in modes:
        data = load_results(mode)
        if not data:
            continue
        n = len(data)
        passed = sum(1 for r in data if r.get("pass"))
        gdsii = sum(1 for r in data if r.get("ppa", {}).get("gdsii_generated"))
        nmeds = [r["nmed"] for r in data if r.get("nmed") is not None]
        avg_nmed = sum(nmeds) / len(nmeds) if nmeds else float("nan")
        avg_iters = sum(r.get("iterations", 1) for r in data) / n
        rows[mode] = {
            "n_specs": n,
            "passed": passed,
            "pass_rate": passed / n,
            "pass@1": compute_pass_at_k(data, 1),
            "pass@3": compute_pass_at_k(data, 3),
            "pass@5": compute_pass_at_k(data, 5),
            "avg_iterations": avg_iters,
            "avg_nmed": avg_nmed,
            "gdsii_rate": gdsii / n,
        }
    return rows


def print_summary_table(modes: list[str] | None = None) -> None:
    """Print a human-readable summary table to stdout."""
    rows = summary_table(modes)
    header = f"{'Mode':<6} {'N':>4} {'Pass':>5} {'Pass@1':>8} {'Pass@3':>8} {'Pass@5':>8} {'Avg Itr':>8} {'Avg NMED':>10} {'GDSII':>7}"
    print(header)
    print("-" * len(header))
    for mode, s in rows.items():
        def fmt(v):
            return f"{v:.3f}" if v == v else "  n/a "
        print(
            f"{mode:<6} {s['n_specs']:>4} {s['passed']:>5}"
            f" {fmt(s['pass@1']):>8} {fmt(s['pass@3']):>8} {fmt(s['pass@5']):>8}"
            f" {s['avg_iterations']:>8.2f} {fmt(s['avg_nmed']):>10} {s['gdsii_rate']:>7.1%}"
        )


def latex_table_e1_e2_e3() -> str:
    """Return LaTeX table comparing E1/E2/E3 with proper pass@k, avg iterations, avg NMED."""
    rows = summary_table(["E1", "E2", "E3"])
    labels = {"E1": "ARCADE-Vanilla", "E2": "ARCADE-Repair", "E3": "ARCADE-Memory"}
    s = (
        "\\begin{tabular}{lcccccc}\n"
        "\\hline\n"
        "Experiment & Pass@1 & Pass@3 & Pass@5 & Avg.~iter. & Avg.~NMED & GDS\\\\\n"
        "\\hline\n"
    )
    for mode in ["E1", "E2", "E3"]:
        if mode not in rows:
            continue
        r = rows[mode]
        def pct(v):
            return f"{v*100:.0f}\\%" if v == v else "---"
        def nmed(v):
            return f"{v*100:.3f}\\%" if v == v else "---"
        s += (
            f"{labels[mode]} & {pct(r['pass@1'])} & {pct(r['pass@3'])} & {pct(r['pass@5'])}"
            f" & {r['avg_iterations']:.1f} & {nmed(r['avg_nmed'])} & {pct(r['gdsii_rate'])}\\\\\n"
        )
    s += "\\hline\n\\end{tabular}"
    return s


def plot_learning_curve_e4() -> Path | None:
    """Plot Pass@1 at first attempt vs design number (E4). Save to FIGURES_DIR."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    data = load_results("E3")
    if not data:
        return None
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    xs = [i + 1 for i in range(len(data))]
    ys = [1 if r.get("pass") else 0 for r in data]
    cumulative = [sum(ys[:i+1]) / (i+1) for i in range(len(ys))]
    fig, ax = plt.subplots()
    ax.bar(xs, ys, alpha=0.4, label="Pass (per spec)")
    ax.plot(xs, cumulative, "o-", color="red", label="Cumulative pass rate")
    ax.set_xlabel("Design number")
    ax.set_ylabel("Pass")
    ax.set_title("RAEM learning curve (E3/E4)")
    ax.legend()
    out = FIGURES_DIR / "e4_learning_curve.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close()
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Print pass@k summary and LaTeX table for experiment results.")
    p.add_argument("--modes", default="E1,E2,E3,E4", help="Comma-separated modes (default: E1,E2,E3,E4)")
    p.add_argument("--latex", action="store_true", help="Also print LaTeX table for E1/E2/E3")
    args = p.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    print_summary_table(modes)
    if args.latex:
        print("\nLaTeX table (E1/E2/E3):\n")
        print(latex_table_e1_e2_e3())
