# Running Full E1–E3 and PPA

To fill Tables I/II in the VTS paper you need: (1) a prepared OpenROAD flow directory and Docker `openroad/orfs` for the PPA loop, and (2) more E1/E2/E3 runs. This doc summarizes both.

---

## 1. Prepare OpenROAD Flow and Docker (for PPA)

### Option A: Use Docker only (recommended for PPA)

You do **not** need a local OpenROAD build. The flow directory only needs the **design source tree** (RTL + configs). The actual tools run inside Docker.

1. **Clone OpenROAD-flow-scripts** (flow layout only; no need to build OpenROAD locally):
   ```bash
   cd /path/to/parent/of/ARCADE
   git clone --depth 1 https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts
   ```
   The flow dir is `OpenROAD-flow-scripts/flow`.

2. **Prepare the APTPU design in the flow** so that `flow/designs/src/aptpu/` and `flow/designs/nangate45/aptpu/` exist with RTL and config.mk. If you use the APTPU/TPU_RL tree, run its setup script (e.g. `setup_aptpu.sh`) from that repo so the flow directory is populated. The PPA loop expects the same layout (designs/src/aptpu, designs/nangate45/aptpu).

3. **Pull the OpenROAD flow Docker image**:
   ```bash
   docker pull openroad/orfs:latest
   ```
   **Note:** The image has no `linux/arm64` build. On Apple Silicon, use emulation:  
   `docker pull --platform linux/amd64 openroad/orfs:latest`  
   If you use a credential helper or private registry, fix Docker login as needed.

4. **Point the orchestrator at the flow** when you want PPA (integrate + run flow):
   ```bash
   cd ARCADE
   source .venv/bin/activate
   export DEEPSEEK_API_KEY=...
   python -m src.orchestrator --mode E2 --limit 1 --flow-root /path/to/OpenROAD-flow-scripts/flow
   ```
   Only runs where an adder **passes NMED** will trigger integration and the PPA loop. So run E2 or E3 with enough specs (or retries) that at least one passes.

### Option B: Native OpenROAD build

If you prefer to run the flow natively (no Docker):

- Build OpenROAD-flow-scripts as usual (`./build_openroad.sh --local`).
- Prepare the APTPU design in the flow (e.g. run your flow’s setup script so the design RTL and config.mk are in place).
- The code currently uses Docker in `ppa_loop.run_openroad_docker`. To use native flow, you would run `make DESIGN_CONFIG=./designs/nangate45/aptpu/config.mk` yourself from `flow/` and ensure `ppa_loop.extract_metrics_from_reports` can read the same report paths (or add a native path in the code).

### Config used by the PPA loop

- **Flow dir:** `OpenROAD-flow-scripts/flow`
- **Design config:** `./designs/nangate45/aptpu/config.mk`
- Reports are read from `flow/results/nangate45/aptpu/base/`, `flow/reports/`, `flow/logs/` (see `ppa_loop.py`).

---

## 2. Run E1, E2, E3 to Fill Tables I/II

### Without PPA (NMED-only)

No flow dir or Docker needed. Pass@1, iterations, and NMED are still recorded.

```bash
cd ARCADE
source .venv/bin/activate
export DEEPSEEK_API_KEY=...

# Quick: 3 specs per mode
python -m src.orchestrator --mode E1 --limit 3
python -m src.orchestrator --mode E2 --limit 3
python -m src.orchestrator --mode E3 --limit 3

# Full: all 13 specs
python -m src.orchestrator --mode E1 --limit 13
python -m src.orchestrator --mode E2 --limit 13
python -m src.orchestrator --mode E3 --limit 13
```

Results go to `results/E1_results.json`, `results/E2_results.json`, `results/E3_results.json`.

### With PPA (integrate + OpenROAD)

Ensure the flow dir is prepared and Docker is available, then pass `--flow-root`:

```bash
python -m src.orchestrator --mode E2 --limit 3 --flow-root /path/to/OpenROAD-flow-scripts/flow
```

When an adder passes NMED, the integrator writes RTL into the flow and the PPA loop runs Docker; PPA metrics are stored in the same result entries (`ppa` dict).

### Generate LaTeX table from results

After E1/E2/E3 have been run:

```bash
cd ARCADE
source .venv/bin/activate
python -c "
from src.results_plotter import latex_table_e1_e2_e3
print(latex_table_e1_e2_e3())
"
```

Copy the printed table into your paper (Table I). For Table II (PPA vs baselines), you need at least one converged design with PPA and baseline runs; baseline numbers can be filled from separate OpenROAD runs as needed.

### One-shot script (E1+E2+E3 then table)

From repo root:

```bash
cd ARCADE && source .venv/bin/activate
python scripts/run_e1_e2_e3.py --limit 3
```

Use `--limit 13` for full runs. Optionally `--flow-root /path/to/flow` to enable PPA for passing adders.

---

## Summary

| Goal | What you need | Command |
|------|----------------|--------|
| Table I (Pass@1, iter, NMED) | API key, no flow | Run E1, E2, E3 with `--limit 13`, then `latex_table_e1_e2_e3()` |
| Table II (PPA) | Flow dir + Docker `openroad/orfs` | Prepare flow with APTPU design, then run E2/E3 with `--flow-root`; fill baselines separately |
| E4 learning curve | E3 results | `results_plotter.plot_learning_curve_e4()` → `figures/e4_learning_curve.pdf` |
