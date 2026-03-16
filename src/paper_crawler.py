"""
Paper crawler: find approximate adder/circuit papers and GitHub repos.
Uses public APIs or URL patterns; no scraping of Google Scholar (would require browser).
Output: list of {title, url, year, github} for use in Design Agent few-shot context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = REPO_ROOT / "configs" / "approx_circuit_papers.json"
PROFESSOR_PAPERS_JSON = REPO_ROOT / "configs" / "professor_papers.json"


# Curated list from plan: approximate adder papers with known citations
CURATED = [
    {"title": "Systematic design of an approximate adder: the optimized lower part constant-OR adder", "year": 2018, "key": "Dalloo2018", "github": ""},
    {"title": "Hardware optimized and error reduced approximate adder", "year": 2019, "key": "Balasubramanian2019", "journal": "Electronics"},
    {"title": "An improved logarithmic multiplier for energy-efficient neural computing", "year": 2021, "key": "Ansari2021", "journal": "IEEE Trans. Comput."},
    {"title": "APTPU: Approximate Computing Based Tensor Processing Unit", "year": 2022, "key": "Elbtity2022APTPU", "journal": "IEEE TCAS-I"},
    {"title": "Approximate arithmetic circuits: a survey", "year": 2020, "key": "Jiang2020", "journal": "Proc. IEEE"},
    {"title": "Low-power digital signal processing using approximate adders", "year": 2013, "key": "Gupta2013", "journal": "IEEE TCAD"},
    {"title": "A survey of techniques for approximate computing", "year": 2016, "key": "Mittal2016", "journal": "ACM Computing Surveys"},
]


def get_curated() -> list[dict[str, Any]]:
    """Return curated list of approximate circuit papers."""
    return list(CURATED)


def fetch_and_cache() -> list[dict[str, Any]]:
    """
    Placeholder: in a full implementation we would call Semantic Scholar API or
    similar to expand the list. For now we write CURATED to cache and return it.
    """
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(CURATED, indent=2))
    return CURATED


def format_for_prompt(papers: list[dict], max_chars: int = 1500) -> str:
    """Format paper list as a short string for Design Agent context."""
    lines = ["Approximate adder references (for style guidance):"]
    for p in papers[:5]:
        lines.append(f"  - {p.get('title', '')} ({p.get('year', '')})")
    s = "\n".join(lines)
    return s[:max_chars]


def load_professor_papers() -> list[dict[str, Any]]:
    """Load papers for context: CURATED + configs/professor_papers.json (professor-shared refs)."""
    out = list(CURATED)
    if PROFESSOR_PAPERS_JSON.exists():
        try:
            extra = json.loads(PROFESSOR_PAPERS_JSON.read_text())
            if isinstance(extra, list):
                out = out + extra
        except Exception:
            pass
    return out[:15]


def get_papers_context_for_design(max_chars: int = 2000) -> str:
    """Return formatted paper context for the Design Agent (curated + professor papers)."""
    papers = load_professor_papers()
    return format_for_prompt(papers, max_chars=max_chars)


if __name__ == "__main__":
    papers = fetch_and_cache()
    print("Cached", len(papers), "papers at", CACHE_FILE)
    print(format_for_prompt(papers))
