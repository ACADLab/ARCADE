"""
RAEM: Retrieval-Augmented Error Memory.
Append-only JSONL store + TF-IDF index for top-k similar past errors/fixes.
Tracks success and failure so agents can avoid repeating failed fixes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
RAEM_FILE = REPO_ROOT / "raem.jsonl"
DESIGN_NUMBER_FILE = REPO_ROOT / "raem_design_counter.txt"


def _next_design_number() -> int:
    p = DESIGN_NUMBER_FILE
    if p.exists():
        n = int(p.read_text().strip())
        p.write_text(str(n + 1))
        return n + 1
    p.write_text("1")
    return 1


def _load_entries() -> list[dict]:
    if not RAEM_FILE.exists():
        return []
    entries = []
    for line in RAEM_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def store(
    session_id: str,
    design_number: int | None,
    error_type: str,
    error_signature: str,
    design_context: dict,
    fix_applied: str = "",
    fix_as_code_delta: str = "",
    nmed_before: float | None = None,
    nmed_after: float | None = None,
    ppa_before: dict | None = None,
    ppa_after: dict | None = None,
    success: bool = False,
    iteration: int = 0,
) -> int:
    """
    Append one RAEM entry. If design_number is None, auto-increment global counter.
    Returns the design_number used.
    """
    if design_number is None:
        design_number = _next_design_number()
    entry = {
        "session_id": session_id,
        "design_number": design_number,
        "error_type": error_type,
        "error_signature": error_signature,
        "design_context": design_context,
        "fix_applied": fix_applied,
        "fix_as_code_delta": fix_as_code_delta,
        "nmed_before": nmed_before,
        "nmed_after": nmed_after,
        "ppa_before": ppa_before or {},
        "ppa_after": ppa_after or {},
        "success": success,
        "iteration": iteration,
    }
    with open(RAEM_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return design_number


def _text_for_vector(entry: dict) -> str:
    parts = [
        entry.get("error_signature", ""),
        entry.get("error_type", ""),
        entry.get("fix_applied", ""),
        json.dumps(entry.get("design_context", {})),
    ]
    return " ".join(str(p) for p in parts)


def query(
    error_signature: str,
    design_context: dict,
    top_k: int = 3,
    success_only: bool = False,
    include_failed_fixes: bool = True,
) -> list[dict]:
    """
    Return top-k most similar past entries. If include_failed_fixes, entries with success=False
    are included so the agent can see what NOT to do; they are still ranked by similarity.
    """
    entries = _load_entries()
    if not entries:
        return []
    if success_only:
        entries = [e for e in entries if e.get("success")]
    text_for = _text_for_vector
    query_text = " ".join([error_signature, json.dumps(design_context)])
    corpus = [text_for(e) for e in entries]
    try:
        vectorizer = TfidfVectorizer(max_features=5000, stop_words="english", token_pattern=r"(?u)\b\w+\b")
        X = vectorizer.fit_transform(corpus)
        q = vectorizer.transform([query_text])
        sims = cosine_similarity(q, X).ravel()
    except Exception:
        return entries[-top_k:] if len(entries) >= top_k else entries
    idx = np.argsort(sims)[::-1][:top_k]
    return [entries[i] for i in idx]


def format_context_for_prompt(entries: list[dict]) -> str:
    """Format top-k entries as a string to prepend to the Design Agent prompt."""
    if not entries:
        return ""
    lines = ["Relevant past fixes from similar designs:"]
    for i, e in enumerate(entries, 1):
        status = "succeeded" if e.get("success") else "failed"
        lines.append(f"  {i}. [{status}] {e.get('error_signature', '')[:80]}... -> {e.get('fix_applied', '')[:60]}...")
    return "\n".join(lines)


if __name__ == "__main__":
    # Smoke test
    store(
        session_id="test",
        design_number=None,
        error_type="nmed_fail",
        error_signature="NMED 0.12 exceeded target 0.05",
        design_context={"bit_width": 8, "family": "LOA"},
        fix_applied="Reduced IMPRECISE_PART from 6 to 4",
        success=True,
        iteration=2,
    )
    entries = query("NMED exceeded target", {"bit_width": 8}, top_k=2)
    print("Query result:", len(entries), entries[0].get("fix_applied") if entries else None)
    print("Prompt context:\n", format_context_for_prompt(entries))
