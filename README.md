# ARCADE

**A**utonomous **R**TL **C**reation with **A**gents, **D**iagnostics, and **E**rror memory — multi-agent approximate adder generation with closed-loop repair and retrieval-augmented error memory (RAEM).

---

## Overview

ARCADE is an LLM-driven framework for generating Verilog approximate adders from minimal specs (`bit_width`, `nmed_target`, `area_priority`). A **Design Agent** produces RTL; a **Verifier Agent** produces a black-box testbench from the same spec; a **golden Verilator harness** computes Normalized Mean Error Distance (NMED) vs exact addition and is the final judge. Passing designs can be wired into an OpenROAD flow for PPA (area, power, timing) evaluation.

### Experiment modes (E1–E4)

| Mode | Name | Description |
|------|------|-------------|
| **E1** | **ARCADE-Vanilla** | Single-shot generation with no repair loop and no retrieval memory, establishing the baseline capability of the underlying model. |
| **E2** | **ARCADE-Repair** | Adds the closed-loop repair mechanism, feeding structured NMED failure diagnostics back to the Design Agent across up to five iterations. |
| **E3** | **ARCADE-Memory** | Augments repair with RAEM retrieval, prepending the top-*k* historically similar failure contexts to each repair prompt. |
| **E4** | **ARCADE-Full** | Same pipeline as E3; used for learning-curve analysis over the spec order (RAEM fills over a sequential run). |

Specs are defined in `configs/adder_specs.json` (13 specs: 8/16/32-bit, varying NMED and area priority). See **implementation.md** for pipeline details.

---

## Prerequisites

- **Python 3.10+**
- **uv** (or pip) for installing the package
- **Verilator** — to compile and run the golden NMED harness
- **API key** — at least one of: DeepSeek (default), Claude, OpenRouter, OpenAI
- **OpenROAD flow** (optional) — only if you want PPA; e.g. Docker `openroad/orfs` or native orfs-build

---

## Setup

Use **uv** to create the virtual environment and install in editable mode (recommended):

```bash
cd ARCADE
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e .
```

Alternatively, use `python -m venv .venv` and `pip install -e .`.

### API keys (required for LLM calls)

Set **environment variables** (recommended for security):

- `DEEPSEEK_API_KEY` (default provider)
- `ANTHROPIC_API_KEY` (for `--provider claude`)
- `OPENROUTER_API_KEY`, `OPENAI_API_KEY` (if using those providers)

Alternatively, you can use a **local keys file** in the repo root (gitignored): create `keys.txt` with PowerShell-style lines, e.g.:

```text
$env:DEEPSEEK_API = 'sk-...'
$env:ANTHROPIC_API_KEY = '...'
```

Do **not** commit `keys.txt` or any file containing secrets.

---

## Directory layout

```
ARCADE/
├── configs/
│   ├── adder_specs.json
│   └── professor_papers.json
├── harness/
│   └── tb_adder.cpp          # Golden NMED harness (Verilator)
├── src/
│   ├── orchestrator.py        # Main entry: modes E1–E4, smoke
│   ├── design_agent.py
│   ├── verifier_agent.py
│   ├── ppa_loop.py            # OpenROAD flow (Docker or native)
│   ├── aptpu_integrator.py    # Injects passing adder into flow
│   └── config.py              # Paths, API key loading
├── results/                   # E1_results.json, E2_results.json, ... (gitignored)
├── work/                      # Per-spec Verilator run dirs (gitignored)
├── run_all_experiments.sh     # E1→E4 with --resume / --start-from
├── implementation.md         # Framework and experiment details
└── docs/
    └── RUNNING_E1_E3_AND_PPA.md
```

---

## Run

### Quick test (single spec, one shot)

```bash
python -m src.orchestrator --mode E1 --spec-id A1 --limit 1
```
(Requires an API key and Verilator.)

### Single mode, few specs (NMED only; no flow required)

```bash
python -m src.orchestrator --mode E1 --limit 3
python -m src.orchestrator --mode E2 --limit 3 --provider deepseek
```

### Single mode with PPA (flow root required)

```bash
python -m src.orchestrator --mode E1 --limit 13 --flow-root /path/to/flow
```

### Full suite (E1 → E4) and resume

```bash
./run_all_experiments.sh --limit 13 --flow-root /path/to/flow
# Resume after partial run:
./run_all_experiments.sh --limit 13 --flow-root /path/to/flow --resume
# Start from E3 only:
./run_all_experiments.sh --limit 13 --flow-root /path/to/flow --resume --start-from E3
```

- **--resume:** Skips modes that already have `limit` results; for partial runs, runs only missing spec IDs and merges.
- **--start-from E2|E3|E4:** Skips earlier modes.
- **--workers N:** Parallel workers per mode (default 4).
- **--with-ppa:** Run PPA inline (1 worker). By default PPA runs as a batch after all verification runs.

Results are written to `results/E1_results.json`, `results/E2_results.json`, etc. Each entry includes `pass`, `nmed`, `ppa` (if flow was run), and `integration` when applicable.

---

## OpenROAD flow (optional)

For PPA you need a prepared flow directory (design RTL + config). See **docs/RUNNING_E1_E3_AND_PPA.md** for:

- Docker-based flow with `openroad/orfs`
- Native orfs-build
- Preparing the APTPU design in the flow

---

## License and citation

See repository metadata. If you use ARCADE in research, please cite the accompanying paper.
