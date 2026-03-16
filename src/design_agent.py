"""
Design Agent: calls LLM (DeepSeek primary, Claude optional) to generate
approximate adder RTL. Receives ONLY the spec (bit_width, nmed_target, area_priority).
Never sees the Verifier Agent's output or the testbench.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import config

DEFAULT_MODEL_DEEPSEEK = "deepseek-chat"
DEFAULT_MODEL_CLAUDE = "claude-sonnet-4-20250514"


def _load_system_prompt() -> str:
    p = Path(__file__).parent.parent / "configs" / "prompt_templates" / "design_agent_system.txt"
    if p.exists():
        return p.read_text()
    return (
        "You are an expert hardware engineer. Generate a synthesizable Verilog approximate adder. "
        "Module name: approx_adder. Parameters: ADDER_LENGTH, IMPRECISE_PART. "
        "Ports: input a, b; output sum (ADDER_LENGTH+1 bits). Output only the Verilog module."
    )


def _user_prompt(
    spec: dict[str, Any],
    raem_context: str = "",
    repair_feedback: str = "",
    papers_context: str = "",
) -> str:
    """Build user prompt from spec only. No family hints. No topology hints."""
    bit_width = spec.get("bit_width", 8)
    nmed_target = spec.get("nmed_target", 0.05)
    area_priority = spec.get("area_priority", "medium")

    lines = [
        f"Design an approximate adder with these constraints:",
        f"- Bit width (ADDER_LENGTH): {bit_width}",
        f"- NMED target: <= {nmed_target}",
        f"- Area priority: {area_priority} (high = minimize area aggressively, low = prioritize accuracy)",
        "",
        "You decide the topology. Output only the Verilog module.",
    ]
    if papers_context:
        lines.extend(["", papers_context])
    if raem_context:
        lines.extend(["", "Context from past designs (errors and fixes):", raem_context])
    if repair_feedback:
        lines.extend(["", "Repair feedback (fix and output corrected Verilog only):", repair_feedback])
    return "\n".join(lines)


def _extract_verilog(text: str) -> str | None:
    for pattern in [r"```(?:verilog|v)\s*\n(.*?)```", r"```\s*\n(.*?)```"]:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r"(\s*module\s+\w+.*?endmodule)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip() if "module" in text and "endmodule" in text else None


def call_deepseek(
    spec: dict[str, Any],
    raem_context: str = "",
    repair_feedback: str = "",
    papers_context: str = "",
) -> tuple[str | None, str, dict]:
    api_key = config.get_deepseek_key_safe()
    if not api_key:
        return None, "", {"error": "DEEPSEEK_API_KEY not set"}
    try:
        import httpx
    except ImportError:
        return None, "", {"error": "httpx not installed"}

    payload = {
        "model": DEFAULT_MODEL_DEEPSEEK,
        "messages": [
            {"role": "system", "content": _load_system_prompt()},
            {"role": "user", "content": _user_prompt(spec, raem_context, repair_feedback, papers_context)},
        ],
        "temperature": 0.4,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=120.0) as client:
        r = client.post("https://api.deepseek.com/v1/chat/completions", json=payload, headers=headers)
    if r.status_code != 200:
        return None, r.text, {"error": f"HTTP {r.status_code}", "body": r.text[:500]}
    data = r.json()
    raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return _extract_verilog(raw), raw, {"usage": data.get("usage", {}), "model": DEFAULT_MODEL_DEEPSEEK}


def call_claude(
    spec: dict[str, Any],
    raem_context: str = "",
    repair_feedback: str = "",
    papers_context: str = "",
) -> tuple[str | None, str, dict]:
    api_key = config.get_anthropic_key_safe()
    if not api_key:
        return None, "", {"error": "ANTHROPIC_API_KEY not set"}
    try:
        from anthropic import Anthropic
    except ImportError:
        return None, "", {"error": "anthropic not installed"}

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=DEFAULT_MODEL_CLAUDE,
        max_tokens=4096,
        temperature=0.4,
        system=_load_system_prompt(),
        messages=[{"role": "user", "content": _user_prompt(spec, raem_context, repair_feedback, papers_context)}],
    )
    raw = msg.content
    if isinstance(raw, list):
        raw = "".join(block.text for block in raw if hasattr(block, "text"))
    else:
        raw = str(raw)
    return _extract_verilog(raw), raw, {"usage": dict(getattr(msg, "usage", {}) or {}), "model": DEFAULT_MODEL_CLAUDE}


def generate(
    spec: dict[str, Any],
    *,
    raem_context: str = "",
    repair_feedback: str = "",
    papers_context: str = "",
    provider: str = "deepseek",
) -> tuple[str | None, str, dict]:
    if provider.lower() == "claude":
        return call_claude(spec, raem_context, repair_feedback, papers_context)
    return call_deepseek(spec, raem_context, repair_feedback, papers_context)
