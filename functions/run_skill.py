"""
run_skill — load a skill from skills/, render its template, call Ollama (or OpenRouter
as free fallback), return output.

Provider priority:
  1. Ollama (local, free, private) — if running
  2. OpenRouter free tier (OPENROUTER_API_KEY + :free suffix) — if Ollama down
  3. Raise RuntimeError — no paid APIs called silently
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime

SKILLS_PATH = os.path.expanduser("~/Desktop/SecondBrain/Projects/ashi/skills")
LOG_PATH = os.path.expanduser("~/Desktop/SecondBrain/AI/agent-logs")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_URL}/api/chat"

# OpenRouter free models (no billing required, rate-limited)
OR_FREE_FAST = os.environ.get("OR_FREE_FAST", "meta-llama/llama-4-scout:free")
OR_FREE_CODE = os.environ.get("OR_FREE_CODE", "deepseek/deepseek-chat-v3-0324:free")

MODEL_MAP = {
    "planner": "ashi-planner",
    "executor": "qwen3:4b",
    "router": "qwen3:0.6b",
    "fallback": "claude-sonnet-4-6",
}

def _ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


class SkillNotFoundError(Exception):
    pass


def _load_skill(skill_name: str, skills_path: str) -> dict:
    """
    Load and parse a skill file. Returns dict with keys:
    name, version, author, model_hint, system, user_template, output_format
    """
    fpath = os.path.join(skills_path, f"{skill_name}.md")
    if not os.path.exists(fpath):
        raise SkillNotFoundError(f"Skill not found: {skill_name} (looked in {fpath})")

    with open(fpath, encoding="utf-8") as f:
        content = f.read()

    # parse frontmatter
    meta: dict = {}
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                meta[k.strip()] = v.strip()
        content = content[fm_match.end():]

    def _extract_section(name: str) -> str:
        m = re.search(
            rf"^## {re.escape(name)}\s*\n(.*?)(?=^##|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    return {
        "name": meta.get("name", skill_name),
        "version": meta.get("version", "1"),
        "author": meta.get("author", "unknown"),
        "model_hint": meta.get("model_hint", "executor"),
        "system": _extract_section("System"),
        "user_template": _extract_section("User Template"),
        "output_format": _extract_section("Output Format"),
    }


def _render_template(template: str, context: dict) -> str:
    """Safe str.format_map — missing keys become {key} unchanged."""
    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(SafeDict(context))


def _call_ollama(system: str, user: str, model: str) -> tuple[str, int]:
    """Returns (response_text, tokens_used). Raises on failure."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())

    text = result["message"]["content"].strip()
    tokens = result.get("eval_count", 0) + result.get("prompt_eval_count", 0)
    return text, tokens


def _call_openrouter(system: str, user: str, model: str) -> tuple[str, int]:
    """OpenRouter with automatic key rotation on 429 rate limit."""
    # Collect all available keys for rotation
    keys = [
        os.environ.get("OPENROUTER_KEY_1", ""),
        os.environ.get("OPENROUTER_KEY_2", ""),
        os.environ.get("OPENROUTER_KEY_3", ""),
    ]
    # Filter empty, deduplicate, fall back to single OPENROUTER_API_KEY
    keys = list(dict.fromkeys(k for k in keys if k))
    if not keys:
        single = os.environ.get("OPENROUTER_API_KEY", "")
        if not single:
            raise RuntimeError("No OPENROUTER_API_KEY set")
        keys = [single]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    data = json.dumps(payload).encode()

    last_error = None
    for i, api_key in enumerate(keys):
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://github.com/basitdev/ashi",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            tokens = result.get("usage", {}).get("total_tokens", 0)
            return text, tokens
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < len(keys) - 1:
                print(f"[run_skill] OpenRouter key {i+1} rate-limited, rotating...", flush=True)
                last_error = e
                continue
            raise
    raise last_error  # type: ignore


def _call_with_fallback(system: str, user: str, model: str) -> tuple[str, int, str]:
    """
    Try Ollama first. If unavailable, fall back to OpenRouter free tier.
    Returns (text, tokens, engine_used).
    """
    if _ollama_available():
        try:
            text, tokens = _call_ollama(system, user, model)
            return text, tokens, f"ollama:{model}"
        except Exception as e:
            print(f"[run_skill] Ollama failed ({e}), trying OpenRouter free tier...")

    # Fallback to OpenRouter free model
    free_model = OR_FREE_CODE if "code" in model.lower() else OR_FREE_FAST
    text, tokens = _call_openrouter(system, user, free_model)
    return text, tokens, f"openrouter:{free_model}"


def _log_skill_run(skill_name: str, model: str, tokens: int) -> None:
    os.makedirs(LOG_PATH, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_PATH, f"{date_str}.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] SKILL skill={skill_name} model={model} tokens={tokens}\n")


def run_skill(
    skill_name: str,
    context: dict,
    model: str = "executor",
    skills_path: str = SKILLS_PATH,
) -> dict:
    """
    Load skill, render template with context, call Ollama, return output.

    Args:
        skill_name:  Name of skill file (without .md)
        context:     Dict of template variables
        model:       Model alias ("planner", "executor", "router") or full model name
        skills_path: Path to skills directory

    Returns:
        {"output": str, "model": str, "tokens_used": int, "skill": str}

    Raises:
        SkillNotFoundError: if skill file doesn't exist
    """
    skill = _load_skill(skill_name, skills_path)

    # resolve model: alias → full name, or use skill hint
    resolved_model = MODEL_MAP.get(model, model)
    if model == "executor" and skill["model_hint"] in MODEL_MAP:
        resolved_model = MODEL_MAP[skill["model_hint"]]

    system_prompt = skill["system"]
    if skill["output_format"]:
        system_prompt += f"\n\nExpected output format:\n{skill['output_format']}"

    user_msg = _render_template(skill["user_template"], context)

    output, tokens, engine = _call_with_fallback(system_prompt, user_msg, resolved_model)
    _log_skill_run(skill_name, engine, tokens)

    return {
        "output": output,
        "model": engine,
        "tokens_used": tokens,
        "skill": skill_name,
    }
