#!/usr/bin/env bash
#
# Run E1, E2, E3, E4 in sequence. With --resume, skips modes that are already
# complete (results file has >= limit entries) and for partial runs (e.g. E3
# has 7/13) runs only the missing spec ids and merges results.
# With --start-from E2, skips E1 and runs from E2 onward.
#
# Usage:
#   ./run_all_experiments.sh --limit 13 --flow-root /path/to/flow
#   ./run_all_experiments.sh --limit 13 --flow-root ... --resume
#   ./run_all_experiments.sh --limit 13 --flow-root ... --resume --start-from E3
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"
SPECS_FILE="$SCRIPT_DIR/configs/adder_specs.json"
MODES=(E1 E2 E3 E4)

LIMIT=13
FLOW_ROOT=""
RESUME=false
START_FROM=""
WORKERS=4       # parallel LLM+Verilator workers per mode (safe for DeepSeek)
WITH_PPA=false  # set to true to run PPA inline (slow); default: PPA runs as a final batch

usage() {
  echo "Usage: $0 [--limit N] [--flow-root PATH] [--resume] [--start-from E1|E2|E3|E4] [--workers N] [--with-ppa]"
  echo "  --limit       Max specs per mode (default: 13)"
  echo "  --flow-root   Path to OpenROAD flow (optional; omit for NMED-only runs)"
  echo "  --resume      Skip complete modes; for partial runs, run only missing spec ids and merge"
  echo "  --start-from  Start from this mode (e.g. E3); earlier modes are skipped"
  echo "  --workers N   Parallel LLM+Verilator workers per mode (default: 4)"
  echo "  --with-ppa    Run PPA inline (1 worker, slow). Default: PPA runs as a final batch after all modes"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit)       LIMIT="$2"; shift 2 ;;
    --flow-root)   FLOW_ROOT="$2"; shift 2 ;;
    --resume)      RESUME=true; shift ;;
    --start-from)  START_FROM="$2"; shift 2 ;;
    --workers)     WORKERS="$2"; shift 2 ;;
    --with-ppa)    WITH_PPA=true; shift ;;
    -h|--help)     usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

# flow-root optional: if omitted, NMED-only runs (--no-ppa); set FLOW_ROOT for PPA
if [[ -z "$FLOW_ROOT" ]]; then
  FLOW_ROOT=""
  echo "Note: No --flow-root; running NMED-only (no PPA). Set --flow-root for PPA."
fi

# Use the same Python as the current shell (venv's python when activated)
PYTHON="${APTPU_PYTHON:-python}"
if ! command -v "$PYTHON" &>/dev/null; then
  PYTHON=python3
fi

# Get ordered list of all spec ids from adder_specs.json
get_all_spec_ids() {
  "$PYTHON" -c "
import json
with open('$SPECS_FILE') as f:
    specs = json.load(f)
print(','.join(s['id'] for s in specs[:$LIMIT]))
"
}

# Get spec ids that are missing from a results file
get_missing_spec_ids() {
  local mode=$1
  local results_file="$RESULTS_DIR/${mode}_results.json"
  if [[ ! -f "$results_file" ]]; then
    # No existing file: all spec ids are "missing" (full run)
    get_all_spec_ids
    return
  fi
  "$PYTHON" -c "
import json
with open('$SPECS_FILE') as f:
    all_specs = json.load(f)
all_ids = [s['id'] for s in all_specs][:$LIMIT]
with open('$results_file') as f:
    existing = json.load(f)
done_ids = {r.get('spec_id') or r.get('id') for r in existing if r.get('spec_id') or r.get('id')}
missing = [i for i in all_ids if i not in done_ids]
if done_ids and not (done_ids & set(all_ids)):
    import sys
    print('WARNING: existing file has spec_ids that do not match current specs (e.g. ' + ','.join(sorted(done_ids)[:3]) + '); running all specs', file=sys.stderr)
    missing = all_ids
print(','.join(missing))
"
}

# Merge partial results: existing file + new results (from last run), output merged by spec order
merge_results() {
  local mode=$1
  local results_file="$RESULTS_DIR/${mode}_results.json"
  local backup_file="${results_file}.bak"
  if [[ ! -f "$backup_file" ]]; then
    return
  fi
  "$PYTHON" -c "
import json
with open('$SPECS_FILE') as f:
    all_specs = json.load(f)
all_ids = [s['id'] for s in all_specs][:$LIMIT]
with open('$backup_file') as f:
    existing = json.load(f)
with open('$results_file') as f:
    new_list = json.load(f)
by_id = {r.get('spec_id'): r for r in existing}
for r in new_list:
    by_id[r.get('spec_id')] = r
merged = [by_id[sid] for sid in all_ids if sid in by_id]
with open('$results_file', 'w') as f:
    json.dump(merged, f, indent=2)
print('Merged', len(new_list), 'new results into', len(merged), 'total for $mode')
"
  rm -f "$backup_file"
}

# Count entries in a mode's results file
count_results() {
  local mode=$1
  local results_file="$RESULTS_DIR/${mode}_results.json"
  if [[ ! -f "$results_file" ]]; then
    echo 0
    return
  fi
  "$PYTHON" -c "
import json
with open('$results_file') as f:
    print(len(json.load(f)))
"
}

# Should we skip this mode? (either start-from or resume and complete)
skip_mode() {
  local mode=$1
  if [[ -n "$START_FROM" ]]; then
    case "$START_FROM" in
      E1) ;;
      E2) [[ "$mode" == "E1" ]] && return 0 ;;
      E3) [[ "$mode" == "E1" || "$mode" == "E2" ]] && return 0 ;;
      E4) [[ "$mode" == "E1" || "$mode" == "E2" || "$mode" == "E3" ]] && return 0 ;;
    esac
  fi
  if $RESUME; then
    local count
    count=$(count_results "$mode")
    if [[ "$count" -ge "$LIMIT" ]]; then
      echo "  [resume] $mode already complete ($count/$LIMIT), skipping"
      return 0
    fi
  fi
  return 1
}

run_mode() {
  local mode=$1
  local missing_spec_ids
  local results_file="$RESULTS_DIR/${mode}_results.json"

  if skip_mode "$mode"; then
    return 0
  fi

  echo "========== $mode =========="
  if $RESUME && [[ -f "$results_file" ]]; then
    local count
    count=$(count_results "$mode")
    if [[ "$count" -gt 0 && "$count" -lt "$LIMIT" ]]; then
      missing_spec_ids=$(get_missing_spec_ids "$mode")
      if [[ -z "$missing_spec_ids" ]]; then
        echo "  [resume] $mode has $count entries, no missing ids"
        return 0
      fi
      echo "  [resume] $mode partial ($count/$LIMIT), running missing: $missing_spec_ids"
      cp "$results_file" "${results_file}.bak"
  if $WITH_PPA; then
    [[ -n "$FLOW_ROOT" ]] || { echo "Error: --with-ppa requires --flow-root"; exit 1; }
    "$PYTHON" -m src.orchestrator --mode "$mode" --spec-ids "$missing_spec_ids" --flow-root "$FLOW_ROOT" --workers 1
  else
    "$PYTHON" -m src.orchestrator --mode "$mode" --spec-ids "$missing_spec_ids" ${FLOW_ROOT:+--flow-root "$FLOW_ROOT"} --no-ppa --workers "$WORKERS"
  fi
      merge_results "$mode"
      return 0
    fi
  fi

  if $WITH_PPA; then
    [[ -n "$FLOW_ROOT" ]] || { echo "Error: --with-ppa requires --flow-root"; exit 1; }
    "$PYTHON" -m src.orchestrator --mode "$mode" --limit "$LIMIT" --flow-root "$FLOW_ROOT" --workers 1
  else
    "$PYTHON" -m src.orchestrator --mode "$mode" --limit "$LIMIT" ${FLOW_ROOT:+--flow-root "$FLOW_ROOT"} --no-ppa --workers "$WORKERS"
  fi
}

# Run PPA in a batch for a given mode: take passing specs from results JSON and run PPA one by one
run_ppa_batch() {
  local mode=$1
  local results_file="$RESULTS_DIR/${mode}_results.json"
  if [[ ! -f "$results_file" ]]; then
    echo "  [ppa-batch] No results file for $mode, skipping"
    return 0
  fi
  local passing_ids=""
  passing_ids=$("$PYTHON" -c "
import json
with open('$results_file') as f:
    data = json.load(f)
# Only run PPA for specs that passed but have no PPA data yet
ids = [r['spec_id'] for r in data if r.get('pass') and not r.get('ppa', {}).get('area_um2')]
print(','.join(ids))
") || true  # don't fail if python errors; passing_ids stays empty
  if [[ -z "$passing_ids" ]]; then
    echo "  [ppa-batch] $mode: all passing specs already have PPA data"
    return 0
  fi
  echo "  [ppa-batch] $mode: running PPA for $passing_ids"
  if [[ -z "$FLOW_ROOT" ]]; then
    echo "  [ppa-batch] Skipping (no --flow-root)"
    return 0
  fi
  cp "$results_file" "${results_file}.bak"
  "$PYTHON" -m src.orchestrator --mode "$mode" --spec-ids "$passing_ids" --flow-root "$FLOW_ROOT" --workers 1
  merge_results "$mode"
}

mkdir -p "$RESULTS_DIR"

# Phase 1: verification runs for all modes (fast, parallel LLM+Verilator, no PPA)
for mode in "${MODES[@]}"; do
  run_mode "$mode"
done

# Phase 2: PPA batch — always runs for specs that passed but have no PPA data yet.
# Only honours START_FROM (not RESUME count) since we want PPA even on complete modes.
should_skip_ppa_mode() {
  local mode=$1
  if [[ -n "$START_FROM" ]]; then
    case "$START_FROM" in
      E2) [[ "$mode" == "E1" ]] && return 0 ;;
      E3) [[ "$mode" == "E1" || "$mode" == "E2" ]] && return 0 ;;
      E4) [[ "$mode" == "E1" || "$mode" == "E2" || "$mode" == "E3" ]] && return 0 ;;
    esac
  fi
  return 1
}

echo ""
echo "========== PPA batch =========="
for mode in "${MODES[@]}"; do
  if should_skip_ppa_mode "$mode"; then continue; fi
  run_ppa_batch "$mode"
done

echo ""
echo "Done. Results: $RESULTS_DIR/*_results.json"
"$PYTHON" -m src.results_plotter --modes "$(IFS=,; echo "${MODES[*]}")"
