# APTPU Agents: Framework and Experiment Implementation

This document explains what the framework is, how the pipeline is implemented in this repository, how the experiments are set up, what is and is not guaranteed by the current verification flow, and how PPA integration works once a generated adder passes the golden judge.

The short version is:

- **Model:** Both Design and Verifier agents use the same LLM per run. Default is **DeepSeek-V3.2** (API id `deepseek-chat`, non–thinking mode, 128K context). See [DeepSeek API Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing). Alternative: `--provider claude` uses Claude Sonnet 4.
- **Framework figure (Mermaid):** The pipeline flow is in `VTS_special_session_march_4/figures/framework.mmd`. Render with `mmdc -i framework.mmd -o framework.pdf` (mermaid-cli) or [mermaid.live](https://mermaid.live).
- The framework is a **two-agent generation and verification pipeline** around a single target module: `approx_adder`.
- The Design Agent is asked to generate RTL from a **minimal spec**: `bit_width`, `nmed_target`, and `area_priority`.
- The Verifier Agent is asked to generate a **black-box testbench** from the same spec, but it is **not** the final judge.
- The **fixed Verilator C++ harness** is the final judge. It computes NMED against **exact addition**, not against a prior approximate-adder baseline.
- If a design passes the golden harness, it can be integrated into the APTPU OpenROAD flow and evaluated for PPA.
- The experiments compare single-shot generation, repair, and repair-plus-memory. They do **not** prove novelty and do **not** formally prove correctness for all widths.

---

## 1. What the Framework Is

The framework is an **LLM-driven approximate-adder generation system** for APTPU.

The object being designed is **not** a full TPU and **not** a full approximate-computing algorithm. The object being designed is one Verilog module with the contract:

- `module approx_adder`
- parameters: `ADDER_LENGTH`, `IMPRECISE_PART`
- ports: `a`, `b`, `sum`

That generated module is later inserted into the APTPU processing-element datapath through the APTPU integration code.

The framework is therefore best described as:

- **input**: a compact adder spec
- **generation**: one LLM proposes RTL
- **independent checking**: another LLM proposes a testbench
- **fixed judging**: a non-LLM golden harness computes NMED
- **optional downstream evaluation**: OpenROAD PPA on the APTPU-integrated design

It is mainly a framework for studying **agent behavior under sparse hardware constraints**, especially whether repair and memory help the generator satisfy numerical error targets more reliably.

---

## 2. Pipeline Overview

The pipeline enforces separation between generation and verification.

1. The **Verifier Agent** receives the spec and generates a self-checking testbench. It never sees the generated RTL before it writes the testbench.
2. The **Design Agent** receives the same spec and generates Verilog. It never sees the Verifier Agent's testbench.
3. These are **two separate API calls with no shared prompt context**.
4. The generated RTL can be run against the Verifier Agent's testbench as an independent sanity check.
5. A **fixed golden-reference C++ harness** compiled with Verilator computes NMED against exact arithmetic. This is the **final judge**.
6. If compilation fails or the measured NMED is above target, repair feedback is sent back to the **Design Agent**, not the Verifier Agent.
7. Once an adder passes the golden harness, the **APTPU integrator** writes it into the OpenROAD flow and the **PPA loop** runs synthesis.
8. RTL that does not pass the golden harness is never integrated.

This flow is implemented in `src/orchestrator.py`: the Verifier Agent is called once from the spec, the Design Agent is called once or multiple times depending on mode, and the golden harness result controls pass/fail and optional integration.

```121:199:aptpu_agents/src/orchestrator.py
    # Verifier Agent: ONE call, sees only the spec, generates testbench
    verifier_tb, verifier_raw, verifier_meta = verifier_generate(spec, provider=provider)

    for it in range(MAX_REPAIR_ITERATIONS):
        if mode == "E1" and it >= 1:
            break

        # Design Agent: gets spec + optional papers + RAEM + repair feedback.
        verilog, raw, meta = design_generate(...)

        # Layer 1: Verifier Agent testbench
        if verifier_tb:
            verifier_result = run_verifier_testbench(verilog, verifier_tb, bit_width)

        # Layer 2: Golden NMED (fixed C++ harness) — this is the FINAL JUDGE
        nmed_result = run_verilator(verilog, bit_width=bit_width, num_samples=100000 if bit_width > 8 else 0)
        ...
        passed = check_nmed_target(nmed_result, nmed_target)
        ...

    if golden_passed and flow_root and flow_root.exists():
        integration = aptpu_integrate(verilog, flow_root=flow_root, dw=bit_width, ww=bit_width, mn=4, mult_dw=8)
        ppa = run_ppa_flow(flow_root=flow_root, timeout_s=1800)
```

---

## 3. What the Design Agent Actually Gets

The Design Agent receives a deliberately small spec:

- `bit_width`
- `nmed_target`
- `area_priority`

No family name is provided. No known topology name is required. No gold reference approximate circuit is provided. The prompt explicitly tells the model to choose the topology itself.

```40:53:aptpu_agents/src/design_agent.py
    lines = [
        f"Design an approximate adder with these constraints:",
        f"- Bit width (ADDER_LENGTH): {bit_width}",
        f"- NMED target: <= {nmed_target}",
        f"- Area priority: {area_priority} (high = minimize area aggressively, low = prioritize accuracy)",
        "",
        "You decide the topology. Output only the Verilog module.",
    ]
```

The system prompt also makes the freedom explicit:

```1:20:aptpu_agents/configs/prompt_templates/design_agent_system.txt
You are an expert hardware engineer. Generate a synthesizable Verilog approximate adder.
...
- You decide the approximation topology. Consider: OR-gating, carry prediction, error compensation, truncation with correction, hybrid carry-select/approximate, speculative carry chains, or novel approaches.
- You will be given an NMED target. Lower NMED = more accurate. Meet the target with minimal area.
```

That means the framework does **not** constrain the Design Agent to rediscover a particular known circuit family, but it also does **not** stop it from generating something that is identical or equivalent to a known approximate adder.

So the right interpretation is:

- the framework is searching for **any adder RTL that satisfies the spec**
- the framework is **not** checking whether that RTL is novel with respect to the literature
- the framework is **not** comparing against a golden approximate-adder implementation

---

## 4. What the Verifier Agent Actually Does

The Verifier Agent receives the **same spec only** and generates a testbench for `approx_adder` treated as a black box.

Its purpose is to create an **independent test artifact** that is not conditioned on the Design Agent's actual RTL. This reduces direct leakage between generator and checker.

However, this verifier testbench is **not the final pass/fail judge**. In the current code:

- the testbench is generated once per spec
- it is run if available
- its result is reported in the output JSON
- the final pass/fail decision still comes from the fixed C++ golden harness

So it is best understood as:

- a sanity check
- an auxiliary verification layer
- not the source of truth

---

## 5. Golden-Reference NMED Harness

The final judge is a **fixed C++ harness** in `harness/tb_adder.cpp` compiled with Verilator.

Important clarification:

- the golden reference is **exact arithmetic**: `a + b`
- there are **no golden approximate-adder circuits**
- the generated adder is not judged by “matching a known baseline adder”
- it is judged by how closely it approximates exact addition under the NMED target in the spec

The harness:

- instantiates the generated `approx_adder`
- drives input pairs `(a, b)`
- computes exact sum in C++
- measures absolute error
- computes average MED and NMED
- reports `max_abs_err`

```33:62:aptpu_agents/harness/tb_adder.cpp
    for (uint64_t i = 0; i < n_tests; i++) {
        ...
        top->a = a32;
        top->b = b32;
        top->eval();
        uint32_t sum_approx = (uint32_t)(top->sum & ((1ULL << (ADDER_LENGTH + 1)) - 1));
        uint64_t exact = (uint64_t)a32 + (uint64_t)b32;
        int64_t err = (int64_t)sum_approx - (int64_t)exact;
        ...
    }

    double med_avg = sum_abs_err / (double)count;
    double avg_exact = sum_exact / (double)count;
    double nmed = (avg_exact != 0) ? (med_avg / fabs(avg_exact)) : med_avg;
```

The current implementation uses:

- **8-bit**: exhaustive enumeration when `num_samples=0`, which is effectively all `2^16` input pairs
- **16/32-bit**: `100000` random samples, because the orchestrator calls `run_verilator(..., num_samples=100000 if bit_width > 8 else 0)`

So the current guarantee is:

- fairly strong empirical checking for 8-bit
- sampled checking, not full proof, for 16-bit and 32-bit

The design passes if:

- it compiles under Verilator
- the harness returns a numeric NMED
- `NMED <= nmed_target`

This is a good functional screen, but it is **not** a formal correctness proof and it is **not** a novelty guarantee.

---

## 6. What “Good Design” Means in This Repo

In this repository, a generated design is considered "good" if it satisfies the current experiment objectives:

- it compiles
- it produces outputs under simulation
- its measured NMED meets the target
- optionally, it can later be integrated and pushed through the PPA flow

This does **not** mean:

- the design is novel
- the design is globally optimal
- the design is provably correct for all larger-width inputs
- the design is different from existing approximate-adder circuits

This point matters because the current framework studies:

- whether an LLM can generate approximate-adder RTL from sparse constraints
- whether repair helps
- whether memory helps

It does **not** yet study:

- equivalence against a library of known approximate adders
- novelty vs prior art
- formal proof obligations

---

## 7. Experiment Setup

### Specs

The experiment set contains **13 specs** in `configs/adder_specs.json`. Each spec contains:

- `id`
- `bit_width`
- `nmed_target`
- `area_priority`

The widths are 8, 16, and 32 bits. The NMED targets vary from loose to strict. `area_priority` is qualitative:

- `high`: bias toward smaller/more aggressive approximate structures
- `medium`: balance area and error
- `low`: bias toward accuracy

### Models and provider

The orchestrator currently supports:

- `deepseek` as default provider
- `claude` as optional provider

### Iterations

- `E1`: one Design Agent attempt only
- `E2`, `E3`, `E4`: up to `MAX_REPAIR_ITERATIONS = 5`

### Flow root and PPA

If `--flow-root` is given and the generated adder passes the golden NMED judge, the orchestrator integrates it into the APTPU flow and runs PPA.

### Output files

Each run writes:

- `results/E1_results.json`
- `results/E2_results.json`
- `results/E3_results.json`
- `results/E4_results.json`

Per-spec output can include:

- `pass`
- `iterations`
- `nmed`
- `max_abs_error`
- verifier status
- `ppa`
- `ppa_success`
- `ppa_log_tail`
- `integration`

---

## 8. The Four Main Experiments (E1–E4)

**Paper names:** *ARCADE-Vanilla* (E1), *ARCADE-Repair* (E2), *ARCADE-Memory* (E3), *ARCADE-Full* (E4).

- **ARCADE-Vanilla (E1):** Single-shot generation with no repair loop and no retrieval memory, establishing the baseline capability of the underlying model.
- **ARCADE-Repair (E2):** Adds the closed-loop repair mechanism, feeding structured NMED failure diagnostics back to the Design Agent across up to five iterations.
- **ARCADE-Memory (E3):** Augments repair with RAEM retrieval, prepending the top-*k* historically similar failure contexts to each repair prompt.
- **ARCADE-Full (E4):** Same pipeline as E3; used for learning-curve analysis over the spec order.

### E1: ARCADE-Vanilla (single-shot baseline)

E1 is the open-loop baseline.

For each spec:

1. Generate verifier testbench once.
2. Generate RTL once.
3. Run the verifier testbench if available.
4. Run the golden harness.
5. If it passes and `flow_root` exists, integrate and run PPA.

What E1 measures:

- raw one-shot success
- how often the model can satisfy the spec without repair
- baseline NMED and PPA-ready yield

### E2: ARCADE-Repair (closed-loop repair)

E2 adds iterative repair but no memory.

For each spec:

1. Generate verifier testbench once.
2. Generate RTL.
3. Run golden harness.
4. If compile fails or NMED fails, send **repair feedback** back to the Design Agent.
5. Retry up to 5 times.

Typical repair feedback contains:

- compile error summary, or
- measured NMED, target NMED, and max absolute error

So the Design Agent gets better **within the same spec** by seeing what failed and being asked to correct it.

### E3: ARCADE-Memory (closed-loop repair plus RAEM)

E3 is E2 plus retrieval-augmented memory.

Before generation, the system queries RAEM using:

- current error signature
- current design context

The Design Agent then receives a short summary of similar past outcomes. This lets it reuse patterns that worked and avoid patterns that failed.

So the Design Agent gets better:

- **within a spec** from repair feedback
- **across specs** from retrieval of earlier successes and failures

### E4: ARCADE-Full (learning-curve mode)

E4 uses the same repair-plus-RAEM pipeline as E3, but the purpose is different: it is intended to measure whether performance improves as RAEM fills up over a sequential run of specs.

Conceptually, E4 asks:

- if the system solves A1, then A2, then A3, does that accumulated memory help later designs pass faster or at first try?

In the current plotting code, the E4 learning-curve visualization is approximated using `E3` result files as a proxy.

---

## 9. Design Agent

The Design Agent receives:

- `bit_width`
- `nmed_target`
- `area_priority`
- optional paper context
- optional RAEM retrieval context
- optional repair feedback

It does **not** receive:

- the Verifier Agent's testbench
- a family label such as LOA or HEAA
- a required topology name
- a golden approximate reference circuit

It must emit exactly one Verilog module named `approx_adder` using the required interface.

This makes the generation task intentionally underspecified. That is both:

- a strength, because it tests whether the agent can design from sparse constraints
- a weakness, because it leaves a lot of freedom and does not tightly benchmark topology selection

---

## 10. Verifier Agent

The Verifier Agent receives only the spec and generates a black-box testbench for `approx_adder`.

It is separated from the Design Agent at prompt time. That separation is useful because it reduces the risk that the verifier simply mirrors the generator's own assumptions.

Still, in the current implementation, the verifier is not sufficient on its own:

- it can fail to generate useful code
- it can miss corner cases
- it is not the final authority

That is why the fixed C++ golden harness remains the final judge.

---

## 11. RAEM: Schema, Retrieval, and Learning

RAEM stands for **Retrieval-Augmented Error Memory**.

The current implementation is an append-only JSONL store in `raem.jsonl` plus a TF-IDF similarity lookup.

Each entry can store:

- `session_id`
- `design_number`
- `error_type`
- `error_signature`
- `design_context`
- `fix_applied`
- `fix_as_code_delta`
- `nmed_before`
- `nmed_after`
- `ppa_before`
- `ppa_after`
- `success`
- `iteration`

In the current orchestrator usage, the most consistently populated fields are:

- `error_type`
- `error_signature`
- `design_context`
- `nmed_after`
- `success`
- `iteration`

`fix_applied` exists in the schema but is not richly populated by the present repair loop. So RAEM today is stronger as an **error/outcome memory** than as a high-fidelity code-edit memory.

Retrieval works by vectorizing the concatenation of:

- error signature
- error type
- fix text
- serialized design context

and ranking entries by cosine similarity.

Both success and failure cases are stored. This matters because the Design Agent can learn not only "what worked" but also "what failed in similar contexts."

One important correction to earlier high-level prose: the current design context does **not** rely on a circuit family label. The repo intentionally removed family hints from the spec.

---

## 12. APTPU Integration

Once a generated adder passes the golden NMED judge, the APTPU integrator modifies the OpenROAD flow tree at four main touchpoints.

1. **Adder RTL**  
   The generated Verilog is written to `designs/src/aptpu/llm_approx_adder.v`.

2. **PE selection**  
   In `pe.v`, the integrator injects:
   - `` `elsif LLM_APPROX_ADDER ``
   - an instantiation of `approx_adder`

3. **Preprocessor define and dimensions**  
   In `options_definitions.vh`, the integrator:
   - sets `` `define LLM_APPROX_ADDER  //APADDER ``
   - updates `DW`, `WW`, `M`, `N`, and `MULT_DW`

4. **Config**  
   In `config.mk`, the integrator appends `llm_approx_adder.v` to the Verilog file list.

This is implemented in `src/aptpu_integrator.py`.

```31:39:aptpu_agents/src/aptpu_integrator.py
def write_adder_rtl(verilog_content: str, flow_root: Path) -> Path:
    """Write adder Verilog to flow/designs/src/aptpu/llm_approx_adder.v."""
```

```40:77:aptpu_agents/src/aptpu_integrator.py
def inject_pe_v(flow_root: Path) -> bool:
    ...
        "`elsif LLM_APPROX_ADDER\n"
        " approx_adder #(.ADDER_LENGTH(OUTWIDTH),.IMPRECISE_PART(IMPRECISE_PART)) ..."
```

Prerequisite:

- the OpenROAD flow tree must already contain the APTPU design scaffold under `designs/nangate45/aptpu` and `designs/src/aptpu`
- this is typically created once via your flow setup (e.g. APTPU/TPU_RL setup script if using that design)

---

## 13. PPA Loop

After integration, the PPA loop runs the OpenROAD flow and parses metrics from reports.

The current implementation supports two execution modes:

- **native make** when the flow root contains a `Makefile` such as `orfs-build/flow`
- **Docker** using `openroad/orfs:latest` otherwise

Before each run, the PPA loop clears previous APTPU artifacts so stale results are not reused. It also copies `options_definitions.vh` into the source tree where needed.

Parsed metrics include:

- `area_um2`
- `utilization_percent`
- `wns_ns`
- `tns_ns`
- `worst_slack_ns`
- power breakdown
- `gdsii_generated`

If the flow fails late, partial metrics can still be recovered from earlier logs. This is especially useful when full GDS is not produced.

One important correction to idealized descriptions: there is **no Feedback Agent** in the current code that closes a PPA-driven optimization loop. PPA is evaluated after golden NMED pass, but the present repair loop is driven by compilation and NMED feedback, not by area/power/wns repair feedback.

---

## 14. What Is Guaranteed and What Is Not

### What the current framework does guarantee

If a design passes, then the current flow has shown that:

- the RTL compiled under Verilator
- the RTL ran under simulation
- the measured NMED met the target on the harness test set
- the max absolute error was observed and recorded
- if PPA was enabled and succeeded, the RTL could be integrated into the APTPU flow and processed by OpenROAD

### What it does not guarantee

The current framework does **not** guarantee:

- novelty with respect to known approximate adders
- equivalence to a published topology
- formal correctness over the full 16/32-bit input space
- global optimality in area-delay-accuracy tradeoff
- that the verifier testbench is complete

So this framework is strong enough to evaluate:

- generation success
- repair effectiveness
- retrieval effectiveness
- approximate functionality under the chosen numerical metric

But it is not yet a full novelty-discovery or formal-verification framework.

---

## 15. Why the Spec Feels Vague

Yes, the spec is intentionally vague.

The Design Agent is given only:

- width
- error target
- qualitative area preference

This is a sparse design brief rather than a tightly constrained hardware synthesis spec.

That means:

- the model has flexibility
- the task is realistic in the sense of “high-level designer intent”
- but evaluation is less controlled than if topology class, delay budget, legal gate set, or exact micro-architecture were fixed

This is why the current framework is better framed as:

- an evaluation of **LLM-driven hardware generation under sparse constraints**

rather than:

- a rigorous benchmark for discovering provably novel approximate adder architectures

---

## 16. Recommended Framing for Paper or README Use

The most accurate high-level framing is:

- We study a **two-agent, separation-enforced generation pipeline** for approximate adders.
- The Design Agent generates RTL from sparse functional and quality constraints.
- The Verifier Agent independently generates a black-box testbench from the same spec.
- A fixed Verilator C++ harness computes NMED against exact arithmetic and is the final pass/fail judge.
- E1, E2, and E3 isolate the effect of one-shot generation, repair, and repair-plus-memory.
- E4 examines whether the memory mechanism improves first-try success over a sequential run.
- Passing designs can be integrated into APTPU and evaluated with OpenROAD for downstream PPA.

That framing is accurate, matches the repository, and avoids overstating novelty or formal guarantees.
