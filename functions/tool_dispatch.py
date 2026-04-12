"""
tool_dispatch — JSON tool router. Models output JSON tool calls, this executes them.
Central hub for all ASHI function tools.
"""
import json
import re
import sys
import os
import shutil
import subprocess
from typing import Callable

# ensure functions/ is on path when called from other directories
_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

# optional — audit may not be importable if not yet installed
try:
    from audit import log_tool as _log_tool
    from audit import log_tool_dispatch as _log_tool_dispatch
except ImportError:

    def _log_tool(name, args_summary, result_summary, duration_ms=None, status="ok"):
        pass

    def _log_tool_dispatch(tool_name, args_keys, success, duration_ms):
        pass


from wiki import search_wiki, append_wiki_log, lint_wiki
from ingest_source import ingest_source
from update_entity import update_entity
from review_task import review_task
from run_skill import run_skill
from run_shell import run_shell
from skill_registry import list_skills, get_skill
from ide_controller import (
    route_task, open_in_ide, switch_model, toggle_copilot,
    install_extension, list_extensions, get_ide_status, smart_open,
)

# optional — observe may not be importable if OTel deps missing
try:
    from observe import emit_metric
except ImportError:
    def emit_metric(name: str, value: float, labels: dict | None = None) -> None:
        pass

# optional — computer control (Phase 2: screen/mouse/keyboard)
try:
    from computer_control import (
        screen_capture, screen_read,
        mouse_move, mouse_click, mouse_scroll,
        keyboard_type, keyboard_key,
        find_on_screen,
        open_app, focus_window,
        screen_understand,
        check_computer_control_health,
    )
    _COMPUTER_CONTROL_AVAILABLE = True
except ImportError:
    _COMPUTER_CONTROL_AVAILABLE = False

# optional — memory manager (Phase 3: Vizier)
try:
    from memory_manager import tool_remember, tool_recall, tool_memory_stats
    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False

# optional — Google Drive (Phase 3: Vizier)
try:
    from gdrive_tool import (
        gdrive_upload, gdrive_download, gdrive_list,
        gdrive_search, gdrive_backup_second_brain, gdrive_status,
    )
    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False

# optional — self-improvement
try:
    from self_improve import tool_get_lessons, tool_get_review
    _SELF_IMPROVE_AVAILABLE = True
except ImportError:
    _SELF_IMPROVE_AVAILABLE = False


def run_opencode(task: str, cwd: str | None = None) -> dict:
    """
    Run a coding task via OpenCode with local Ollama (qwen2.5-coder:14b).
    Zero API cost. Returns output, exit_code, and any error text.
    """
    binary = shutil.which("opencode") or os.path.expanduser("~/.opencode/bin/opencode")
    if not os.path.isfile(binary):
        return {"output": "", "exit_code": 1, "error": "opencode binary not found"}

    cmd = [binary, "run", "--model", "ollama/qwen2.5-coder:14b", task]
    work_dir = os.path.expanduser(cwd) if cwd else None

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=work_dir,
        )
        return {
            "output": result.stdout,
            "exit_code": result.returncode,
            "error": result.stderr if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "exit_code": 124, "error": "opencode timed out after 300s"}
    except Exception as e:
        return {"output": "", "exit_code": 1, "error": str(e)}


# optional — TCU creation
_TASKS_PATH = os.path.expanduser("~/Desktop/SecondBrain/tasks")

try:
    from tcu import TCU
    def create_tcu(intent: str, project: str = "ashi", tasks_path: str = _TASKS_PATH) -> dict:
        tcu = TCU.create(intent, project, tasks_path)
        return {"tcu_id": tcu._data["id"], "status": tcu._data["status"]}
except ImportError:
    def create_tcu(intent: str, project: str = "ashi", tasks_path: str = _TASKS_PATH) -> dict:
        return {"error": "TCU module not available"}


TOOL_REGISTRY: dict[str, Callable] = {
    "search_wiki": search_wiki,
    "append_wiki_log": append_wiki_log,
    "lint_wiki": lint_wiki,
    "ingest_source": ingest_source,
    "update_entity": update_entity,
    "review_task": review_task,
    "run_skill": run_skill,
    "create_tcu": create_tcu,
    "emit_metric": emit_metric,
    "list_skills": lambda system="all": list_skills(system),
    "get_skill_info": lambda name: get_skill(name) or {"error": f"skill '{name}' not found"},
    "run_shell": run_shell,
    "opencode": run_opencode,
    # IDE control
    "ide_route":             route_task,
    "ide_open":              open_in_ide,
    "ide_switch_model":      switch_model,
    "ide_toggle_copilot":    toggle_copilot,
    "ide_install_extension": install_extension,
    "ide_list_extensions":   list_extensions,
    "ide_status":            get_ide_status,
    "ide_smart_open":        smart_open,
}

# Register computer control tools if available
if _COMPUTER_CONTROL_AVAILABLE:
    TOOL_REGISTRY.update({
        # Screen tools
        "screen_capture":    screen_capture,
        "screen_read":       screen_read,
        "screen_understand": screen_understand,
        "find_on_screen":    find_on_screen,
        # Mouse tools
        "mouse_move":        mouse_move,
        "mouse_click":       mouse_click,
        "mouse_scroll":      mouse_scroll,
        # Keyboard tools
        "keyboard_type":     keyboard_type,
        "keyboard_key":      keyboard_key,
        # Window/App management
        "open_app":          open_app,
        "focus_window":      focus_window,
        # Health check
        "cc_health":         check_computer_control_health,
    })

# Register memory tools if available
if _MEMORY_AVAILABLE:
    TOOL_REGISTRY.update({
        "remember":       tool_remember,
        "recall":         tool_recall,
        "memory_stats":   tool_memory_stats,
    })

# Register Google Drive tools if available
if _GDRIVE_AVAILABLE:
    TOOL_REGISTRY.update({
        "gdrive_upload":   gdrive_upload,
        "gdrive_download": gdrive_download,
        "gdrive_list":     gdrive_list,
        "gdrive_search":   gdrive_search,
        "gdrive_backup":   gdrive_backup_second_brain,
        "gdrive_status":   gdrive_status,
    })

# Register self-improvement tools if available
if _SELF_IMPROVE_AVAILABLE:
    TOOL_REGISTRY.update({
        "get_lessons":  tool_get_lessons,
        "get_review":   tool_get_review,
    })


def dispatch(tool_call: dict) -> dict:
    """
    Execute a single tool call dict.

    Args:
        tool_call: {"tool": "<name>", "args": {<kwargs>}}

    Returns:
        Tool result dict, or {"error": str, "tool": str}
    """
    if not isinstance(tool_call, dict):
        return {"error": "tool_call must be a dict"}

    tool_name = tool_call.get("tool", "")
    args = tool_call.get("args", {})

    if not tool_name:
        return {"error": "missing 'tool' key"}

    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        available = sorted(TOOL_REGISTRY.keys())
        return {
            "error": f"unknown tool '{tool_name}'",
            "available": available,
        }

    if not isinstance(args, dict):
        return {"error": "'args' must be a dict", "tool": tool_name}

    import time as _time
    _t0 = _time.perf_counter()
    try:
        result = fn(**args)
        _duration_ms = (_time.perf_counter() - _t0) * 1000
        emit_metric(
            "ashi_tool_dispatch_total",
            1.0,
            {"tool": tool_name, "status": "ok"},
        )
        result = result if isinstance(result, dict) else {"result": result}
        _log_tool(tool_name, str(args)[:100], str(result)[:100], _duration_ms, "ok")
        _log_tool_dispatch(tool_name, list(args.keys()), True, _duration_ms)
        return result
    except TypeError as e:
        _duration_ms = (_time.perf_counter() - _t0) * 1000
        emit_metric(
            "ashi_tool_dispatch_total",
            1.0,
            {"tool": tool_name, "status": "arg_error"},
        )
        _log_tool(tool_name, str(args)[:100], str(e)[:100], _duration_ms, "error")
        _log_tool_dispatch(tool_name, list(args.keys()), False, _duration_ms)
        return {"error": f"argument error: {e}", "tool": tool_name}
    except Exception as e:
        _duration_ms = (_time.perf_counter() - _t0) * 1000
        emit_metric(
            "ashi_tool_dispatch_total",
            1.0,
            {"tool": tool_name, "status": "error"},
        )
        _log_tool(tool_name, str(args)[:100], str(e)[:100], _duration_ms, "error")
        _log_tool_dispatch(tool_name, list(args.keys()), False, _duration_ms or 0)
        return {"error": str(e), "tool": tool_name}


def extract_tool_calls(llm_response: str) -> list[dict]:
    """
    Extract tool call JSON blocks from an LLM response.
    Handles:
      - ```json {...} ``` fenced blocks
      - bare {...} blocks containing a "tool" key

    Returns list of valid tool call dicts (must have "tool" key).
    """
    calls: list[dict] = []

    # fenced blocks first
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", llm_response, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "tool" in obj:
                calls.append(obj)
        except json.JSONDecodeError:
            pass

    # bare JSON objects (only if no fenced blocks found)
    if not calls:
        for m in re.finditer(r"\{[^{}]*\"tool\"[^{}]*\}", llm_response):
            try:
                obj = json.loads(m.group(0))
                if isinstance(obj, dict) and "tool" in obj:
                    calls.append(obj)
            except json.JSONDecodeError:
                pass

    return calls


def dispatch_all(llm_response: str) -> list[dict]:
    """
    Extract all tool calls from an LLM response and execute them.

    Returns list of results in call order.
    """
    calls = extract_tool_calls(llm_response)
    return [dispatch(call) for call in calls]


def list_tools() -> list[dict]:
    """Return available tool names and their docstrings."""
    return [
        {
            "name": name,
            "description": (fn.__doc__ or "").strip().split("\n")[0],
        }
        for name, fn in sorted(TOOL_REGISTRY.items())
    ]
