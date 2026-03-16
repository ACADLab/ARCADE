"""Load API keys and paths. Keys from environment only (or optional keys.txt in repo root, gitignored)."""
import os
from pathlib import Path

# Repo root (ARCADE/)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Optional: parent dirs for TPU_RL / OpenROAD flow (set by user or leave unset)
# For PPA you must pass --flow-root or set FLOW_ROOT env to a prepared flow directory.
TPU_RL_DIR = Path(os.environ.get("TPU_RL_DIR", "")).resolve() if os.environ.get("TPU_RL_DIR") else REPO_ROOT.parent / "TPU_RL"
if not TPU_RL_DIR.exists():
    TPU_RL_DIR = None

OPENROAD_FLOW_DIR = Path(os.environ.get("FLOW_ROOT", "")).resolve() if os.environ.get("FLOW_ROOT") else None
if OPENROAD_FLOW_DIR and not OPENROAD_FLOW_DIR.exists():
    OPENROAD_FLOW_DIR = None


def get_anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def get_deepseek_key() -> str:
    return os.environ.get("DEEPSEEK_API_KEY", "")


def get_openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "")


def get_openai_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "")


# Optional keys file in repo root (gitignored) — PowerShell-style $env:KEY = 'value'
_KEYS_FILE = REPO_ROOT / "keys.txt"


def _parse_keys_file():
    env = {}
    if not _KEYS_FILE.exists():
        return env
    try:
        text = _KEYS_FILE.read_text()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("$env:") and "=" in line:
                rest = line[5:].split("=", 1)
                key = rest[0].strip()
                val = rest[1].strip().strip("'\"")
                if key == "HF_TOKEN":
                    env["HF_TOKEN"] = val
                elif key == "OPENAI_API_KEY":
                    env["OPENAI_API_KEY"] = val
                elif key == "OPENROUTER_API":
                    env["OPENROUTER_API_KEY"] = val
                elif key == "DEEPSEEK_API":
                    env["DEEPSEEK_API_KEY"] = val
                elif key == "ANTHROPIC_API_KEY":
                    env["ANTHROPIC_API_KEY"] = val
    except Exception:
        pass
    return env


_parsed = _parse_keys_file()


def get_anthropic_key_safe():
    return get_anthropic_key() or _parsed.get("ANTHROPIC_API_KEY", "")


def get_deepseek_key_safe():
    return get_deepseek_key() or _parsed.get("DEEPSEEK_API_KEY", "")


def get_openrouter_key_safe():
    return get_openrouter_key() or _parsed.get("OPENROUTER_API_KEY", "")


def get_openai_key_safe():
    return get_openai_key() or _parsed.get("OPENAI_API_KEY", "")
