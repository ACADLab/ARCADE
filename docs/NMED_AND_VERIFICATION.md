# NMED and Verification

## What is NMED?

**NMED (Normalized Mean Error Distance)** is the metric we use to decide whether an approximate adder meets the spec. It is defined as:

- **MED_avg** = (1/N) × Σᵢ |P_exact,i − P_approx,i|  (mean absolute error over N test vectors)
- **NMED** = MED_avg / |Avg(P_exact)|  where Avg(P_exact) = (1/N) × Σᵢ P_exact,i

So NMED normalizes the mean absolute error by the mean of the exact sums. This matches the definition in the APTPU literature (e.g. Elbtity et al.). The adder **passes** iff NMED ≤ spec’s `nmed_target`.

## How we verify (correct and unfakeable)

1. **Golden reference**  
   The exact sum P_exact = a + b is computed in **C++** in the Verilator testbench (`harness/tb_adder.cpp`). The LLM never sees or modifies this code.

2. **DUT**  
   The LLM-generated Verilog is compiled with Verilator and simulated. We read the `sum` output from the DUT.

3. **NMED**  
   We compute MED_avg and NMED in the same C++ testbench from:
   - P_exact = a + b (C++)
   - P_approx = DUT sum (from Verilator)

   So the metric cannot be gamed: the model cannot “output” a fake NMED; it can only change the RTL. Either the RTL satisfies the bound or it does not.

4. **Test vectors**  
   - 8-bit: exhaustive (all 2¹⁶ input pairs).  
   - 16/32-bit: stratified random (100k samples by default) to keep runtime bounded.

## LLM generation mode

- **E1 — Single-shot (no feedback)**  
  One call per spec. No repair: if the first RTL fails NMED or compile, we do not call the LLM again for that spec.

- **E2 — Single-shot with feedback**  
  One call per attempt, but we allow up to 5 attempts per spec. After each failure we send a **repair prompt** (e.g. “NMED 0.08 exceeded target 0.05. Reduce approximation…”) and the LLM returns revised Verilog. So: single-shot per request, with iterative feedback across requests.

- **E3 — Single-shot with feedback + RAEM**  
  Same as E2, plus we inject **retrieved past (error, fix, outcome)** from RAEM into the prompt so the model can reuse successful fixes and avoid repeating failed ones.

We do **not** use multi-shot in the sense of multiple fixed examples in one prompt (no few-shot examples in the current system prompt). So: **single-shot generation per call; E2/E3 add feedback (and E3 adds RAEM).**
