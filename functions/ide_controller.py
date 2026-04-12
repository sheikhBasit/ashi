"""
ide_controller.py — ASHI IDE Controller
Controls VS Code, Cursor, and Antigravity: open files, switch models,
manage extensions, toggle Copilot, route tasks to the right IDE.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

# optional — audit may not be available during early boot
try:
    from audit import log_ide_action as _log_ide_action
except ImportError:
    def _log_ide_action(action: str, ide: str, path: str, model: str) -> None:
        pass

# ── IDE definitions ────────────────────────────────────────────────────────────

IDE = Literal["code", "cursor", "antigravity"]

IDE_BINS: dict[str, str] = {
    "code":        "code",
    "vscode":      "code",
    "cursor":      "cursor",
    "antigravity": "antigravity",
    "ag":          "antigravity",
}

SETTINGS_PATHS: dict[str, Path] = {
    "code":        Path.home() / ".config/Code/User/settings.json",
    "cursor":      Path.home() / ".config/Cursor/User/settings.json",
    "antigravity": Path.home() / ".config/Antigravity/User/settings.json",
}

# ── Task → IDE routing rules ───────────────────────────────────────────────────
# ASHI decides which IDE to use based on task type and cost preference.

ROUTING_RULES = [
    # Zero-cost local tasks → OpenCode (Ollama)
    {"tags": ["local", "zero-cost", "bulk", "refactor"], "ide": "opencode",  "model": "ollama/qwen2.5-coder:14b"},
    # PHP / Java / multi-language → Antigravity (has those extensions)
    {"tags": ["php", "java", "ruby", "go"],              "ide": "antigravity", "model": "claude"},
    # AI-heavy / Copilot tasks → VS Code (Copilot installed)
    {"tags": ["copilot", "completion", "inline"],        "ide": "code",        "model": "copilot"},
    # Default coding → Cursor (Claude Code + Cursor AI)
    {"tags": ["code", "feature", "fix", "debug"],        "ide": "cursor",      "model": "claude"},
    # Research / writing → Claude Code CLI (current session)
    {"tags": ["research", "wiki", "plan", "write"],      "ide": "claude-code", "model": "claude"},
]

# ── Model profiles ─────────────────────────────────────────────────────────────
# These are settings.json keys injected per IDE when switching models.

MODEL_PROFILES: dict[str, dict] = {
    "claude": {
        # Claude Code handles this — nothing to inject into settings.json
        "claudeCode.preferredLocation": "panel",
    },
    "copilot": {
        "github.copilot.enable": {"*": True},
        "github.copilot.editor.enableAutoCompletions": True,
    },
    "copilot-off": {
        "github.copilot.enable": {"*": False},
        "github.copilot.editor.enableAutoCompletions": False,
    },
    "ollama": {
        # Cursor: use Ollama via OpenAI-compatible endpoint
        "cursor.general.openaiApiKey":    "ollama",
        "cursor.general.openaiBaseUrl":   "http://localhost:11434/v1",
        "cursor.cpp.defaultModel":        "qwen2.5-coder:14b",
    },
    "gpt-4o": {
        "cursor.cpp.defaultModel": "gpt-4o",
    },
    "gpt-4.1": {
        "cursor.cpp.defaultModel": "gpt-4.1",
    },
    "claude-sonnet": {
        "cursor.cpp.defaultModel": "claude-sonnet-4-5",
    },
}


# ── Core helpers ───────────────────────────────────────────────────────────────

def _bin(ide: str) -> str | None:
    name = IDE_BINS.get(ide.lower(), ide)
    return shutil.which(name)


def _read_settings(ide: str) -> dict:
    path = SETTINGS_PATHS.get(ide.lower())
    if not path or not path.exists():
        return {}
    text = path.read_text()
    # Strip JS-style comments (// ...) before parsing
    import re
    text = re.sub(r"//.*", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _write_settings(ide: str, settings: dict) -> bool:
    path = SETTINGS_PATHS.get(ide.lower())
    if not path:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=4))
    return True


# ── Public API ─────────────────────────────────────────────────────────────────

def route_task(task: str, tags: list[str] | None = None) -> dict:
    """
    Given a task description and optional tags, return the best IDE + model.
    Returns: {"ide": str, "model": str, "reason": str}
    """
    tags = [t.lower() for t in (tags or [])]
    task_lower = task.lower()

    # Auto-detect tags from task text if not provided
    auto_tags: list[str] = []
    tag_keywords = {
        "php": ["php", ".php"], "java": ["java", ".java", "spring"],
        "ruby": ["ruby", ".rb", "rails"], "go": ["golang", ".go"],
        "refactor": ["refactor", "rename", "restructure"],
        "copilot": ["copilot", "autocomplete", "completion"],
        "local": ["local", "offline", "zero-cost", "free"],
        "bulk": ["bulk", "batch", "many files"],
        "code": ["implement", "build", "write code", "function", "class"],
        "fix": ["fix", "bug", "error", "crash", "broken"],
        "debug": ["debug", "trace", "stack", "exception"],
        "research": ["research", "find", "explain", "what is"],
        "wiki": ["wiki", "document", "note"],
        "plan": ["plan", "roadmap", "strategy", "design"],
    }
    for tag, keywords in tag_keywords.items():
        if any(kw in task_lower for kw in keywords):
            auto_tags.append(tag)

    all_tags = set(tags + auto_tags)

    for rule in ROUTING_RULES:
        rule_tags = set(rule["tags"])
        if rule_tags & all_tags:
            return {
                "ide":    rule["ide"],
                "model":  rule["model"],
                "reason": f"matched tags: {rule_tags & all_tags}",
                "tags":   list(all_tags),
            }

    # Default
    return {"ide": "cursor", "model": "claude", "reason": "default", "tags": list(all_tags)}


def open_in_ide(
    path: str,
    ide: str = "cursor",
    line: int | None = None,
    new_window: bool = False,
) -> dict:
    """
    Open a file or folder in the specified IDE.
    path: file path or directory
    line: optional line number (file:line)
    """
    bin_path = _bin(ide)
    if not bin_path:
        return {"ok": False, "error": f"IDE not found: {ide}"}

    target = path
    if line is not None:
        target = f"{path}:{line}"

    cmd = [bin_path]
    if new_window:
        cmd += ["--new-window"]
    if line is not None:
        cmd += ["--goto", target]
    else:
        cmd += [path]

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _log_ide_action("open", ide, path, "default")
        return {"ok": True, "ide": ide, "path": path, "line": line}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def switch_model(ide: str, model: str) -> dict:
    """
    Switch the AI model for the given IDE by writing to its settings.json.
    model: one of the keys in MODEL_PROFILES, or a raw settings dict.
    """
    if ide.lower() == "opencode":
        return _switch_opencode_model(model)

    profile = MODEL_PROFILES.get(model)
    if not profile:
        return {"ok": False, "error": f"Unknown model profile: {model}. Available: {list(MODEL_PROFILES.keys())}"}

    settings = _read_settings(ide)
    settings.update(profile)
    ok = _write_settings(ide, settings)
    if ok:
        _log_ide_action("switch_model", ide, "", model)
    return {"ok": ok, "ide": ide, "model": model, "applied": profile}


def _switch_opencode_model(model: str) -> dict:
    config_path = Path.home() / ".config/opencode/config.json"
    if not config_path.exists():
        return {"ok": False, "error": "OpenCode config not found"}
    config = json.loads(config_path.read_text())
    model_map = {
        "qwen2.5-coder": "ollama/qwen2.5-coder:14b",
        "qwen3":         "ollama/qwen3:0.6b",
        "claude":        "anthropic/claude-sonnet-4-6",
        "claude-sonnet": "anthropic/claude-sonnet-4-6",
    }
    resolved = model_map.get(model, model)
    config["model"] = resolved
    config_path.write_text(json.dumps(config, indent=2))
    return {"ok": True, "ide": "opencode", "model": resolved}


def toggle_copilot(enable: bool, ide: str = "code") -> dict:
    """Enable or disable GitHub Copilot in the given IDE."""
    model_key = "copilot" if enable else "copilot-off"
    return switch_model(ide, model_key)


def install_extension(ide: str, extension_id: str) -> dict:
    """Install a VS Code-compatible extension in the given IDE."""
    bin_path = _bin(ide)
    if not bin_path:
        return {"ok": False, "error": f"IDE not found: {ide}"}
    try:
        result = subprocess.run(
            [bin_path, "--install-extension", extension_id],
            capture_output=True, text=True, timeout=60,
        )
        ok = result.returncode == 0
        return {
            "ok": ok,
            "ide": ide,
            "extension": extension_id,
            "output": (result.stdout + result.stderr).strip()[-500:],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_extensions(ide: str) -> dict:
    """List installed extensions for the given IDE."""
    bin_path = _bin(ide)
    if not bin_path:
        return {"ok": False, "error": f"IDE not found: {ide}"}
    try:
        result = subprocess.run(
            [bin_path, "--list-extensions", "--show-versions"],
            capture_output=True, text=True, timeout=15,
        )
        exts = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return {"ok": True, "ide": ide, "extensions": exts, "count": len(exts)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_ide_status() -> dict:
    """Return current status of all IDEs: installed, version, active extensions."""
    status = {}
    for ide_key, bin_name in [("code", "code"), ("cursor", "cursor"), ("antigravity", "antigravity"), ("opencode", "opencode")]:
        bin_path = shutil.which(bin_name) or shutil.which(
            str(Path.home() / f".opencode/bin/{bin_name}")
        )
        if not bin_path:
            status[ide_key] = {"installed": False}
            continue
        try:
            result = subprocess.run(
                [bin_path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            version = result.stdout.strip().split("\n")[0]
            status[ide_key] = {"installed": True, "version": version, "bin": bin_path}
        except Exception:
            status[ide_key] = {"installed": True, "bin": bin_path, "version": "?"}

    # Add current model settings per IDE
    for ide in ["code", "cursor", "antigravity"]:
        if status.get(ide, {}).get("installed"):
            s = _read_settings(ide)
            status[ide]["copilot_enabled"] = s.get("github.copilot.enable", {}).get("*", False) if isinstance(s.get("github.copilot.enable"), dict) else s.get("github.copilot.enable", False)
            status[ide]["cursor_model"] = s.get("cursor.cpp.defaultModel", "default")

    return status


def smart_open(task: str, path: str, tags: list[str] | None = None) -> dict:
    """
    Route a task to the best IDE and open the given path in it.
    This is the main entry point ASHI uses for IDE control.
    """
    route = route_task(task, tags)
    ide = route["ide"]

    if ide == "opencode":
        # Launch OpenCode in the project directory
        opencode_bin = shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode")
        try:
            subprocess.Popen(
                [opencode_bin],
                cwd=path if os.path.isdir(path) else str(Path(path).parent),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return {"ok": True, "ide": "opencode", "model": route["model"], "path": path, "reason": route["reason"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if ide == "claude-code":
        return {"ok": True, "ide": "claude-code", "model": "claude", "path": path,
                "note": "Run: claude in the project terminal", "reason": route["reason"]}

    result = open_in_ide(path, ide)
    result["model"] = route["model"]
    result["reason"] = route["reason"]
    return result
