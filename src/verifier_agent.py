"""
Verifier Agent: separate LLM call that generates a testbench from ONLY the spec.
Never sees the Design Agent's output. Never sees the RTL.
The golden-reference NMED (fixed C++ harness) is the final judge regardless.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import config

DEFAULT_MODEL_DEEPSEEK = "deepseek-chat"
DEFAULT_MODEL_CLAUDE = "claude-sonnet-4-20250514"


def _load_system_prompt() -> str:
    p = Path(__file__).parent.parent / "configs" / "prompt_templates" / "verifier_agent_system.txt"
    if p.exists():
        return p.read_text()
    return (
        "You are a hardware verification engineer. Generate a Verilog testbench for an approximate adder "
        "module approx_adder. Compute NMED = mean_abs_error / mean_exact_sum. Print NMED and PASS/FAIL."
    )


def _user_prompt(spec: dict[str, Any]) -> str:
    """Build user prompt from spec only. No RTL. No topology hints."""
    bit_width = spec.get("bit_width", 8)
    nmed_target = spec.get("nmed_target", 0.05)

    return "\n".join([
        f"Generate a testbench for an approximate adder with:",
        f"- ADDER_LENGTH = {bit_width}",
        f"- NMED pass threshold: <= {nmed_target}",
        f"- IMPRECISE_PART = {bit_width // 4} (default; the DUT decides how to use it)",
        "",
        "Treat the DUT as a black box. Output only the testbench Verilog.",
    ])


def _extract_verilog(text: str) -> str | None:
    for pattern in [r"```(?:systemverilog|sv|verilog|v)\s*\n(.*?)```", r"```\s*\n(.*?)```"]:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r"(\s*module\s+\w+.*?endmodule)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip() if "module" in text.lower() and "endmodule" in text.lower() else None


def call_deepseek(spec: dict[str, Any]) -> tuple[str | None, str, dict]:
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
            {"role": "user", "content": _user_prompt(spec)},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=120.0) as client:
        r = client.post("https://api.deepseek.com/v1/chat/completions", json=payload, headers=headers)
    if r.status_code != 200:
        return None, r.text, {"error": f"HTTP {r.status_code}"}
    data = r.json()
    raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return _extract_verilog(raw), raw, {"model": DEFAULT_MODEL_DEEPSEEK}


def call_claude(spec: dict[str, Any]) -> tuple[str | None, str, dict]:
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
        temperature=0.2,
        system=_load_system_prompt(),
        messages=[{"role": "user", "content": _user_prompt(spec)}],
    )
    raw = msg.content
    if isinstance(raw, list):
        raw = "".join(block.text for block in raw if hasattr(block, "text"))
    else:
        raw = str(raw)
    return _extract_verilog(raw), raw, {"model": DEFAULT_MODEL_CLAUDE}


def generate_testbench(
    spec: dict[str, Any],
    *,
    provider: str = "deepseek",
) -> tuple[str | None, str, dict]:
    """Generate a testbench from the spec only. Never sees the design RTL."""
    if provider.lower() == "claude":
        return call_claude(spec)
    return call_deepseek(spec)
