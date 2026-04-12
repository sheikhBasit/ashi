# functions/task_agent.py
"""
TaskAgent — executes a single step from the Blackboard plan.
Uses qwen3:4b to pick the right tool + args, then dispatches via tool_dispatch.
"""
import json
import os
import re
import sys

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

from run_skill import _call_with_fallback
from tool_dispatch import dispatch
from action_classifier import classify_action, ActionRisk
from blackboard import Blackboard

EXECUTOR_MODEL = os.environ.get("ASHI_EXECUTOR_MODEL", "qwen3:4b")

_SYSTEM_PROMPT = """\
You are ASHI's execution agent. You receive a single task step and output \
exactly one JSON tool call to complete it. No explanation. Only JSON.

Available tools and their args:
- search_wiki: {"query": str, "wiki_path": "~/Desktop/SecondBrain/wiki", "top_k": 5}
- run_shell: {"command": str, "cwd": str (optional), "timeout": 30}
- run_skill: {"skill_name": str, "context": {dict of template vars}}
- ingest_source: {"url": str, "label": str}
- update_entity: {"entity_name": str, "entity_type": str, "new_facts": str}
- append_wiki_log: {"log_path": str, "entry": str}
- list_skills: {"system": "all"}
- opencode: {"task": str, "cwd": str (optional)}

Computer control tools:
- screen_capture: {"region": "x,y,w,h" (optional), "output_format": "path"|"base64"}
- screen_read: {"region": "x,y,w,h" (optional), "image_path": str (optional), "lang": "eng"}
- screen_understand: {"question": str, "image_path": str (optional), "region": "x,y,w,h" (optional)}
- find_on_screen: {"text": str, "region": "x,y,w,h" (optional), "confidence": 0.6}
- mouse_move: {"x": int, "y": int, "absolute": true}
- mouse_click: {"button": "left"|"right"|"middle", "x": int (optional), "y": int (optional), "clicks": 1}
- mouse_scroll: {"direction": "up"|"down", "amount": 3}
- keyboard_type: {"text": str, "delay_ms": 12}
- keyboard_key: {"keys": "ctrl+c"|"alt+tab"|"super"|"return" etc}
- open_app: {"app_name": str, "args": str (optional)}
- focus_window: {"window_name": str}

Output format (JSON only, no markdown fences):
{"tool": "<tool_name>", "args": {<args>}}
"""

_USER_TEMPLATE = """\
Context so far:
{context}

Step to execute: {step}

Output the JSON tool call:
"""


def _call_ollama(system: str, user: str, model: str) -> tuple[str, int]:
    """Thin wrapper so tests can patch it."""
    text, tokens, _ = _call_with_fallback(system, user, model)
    return text, tokens


def _extract_tool_call(raw: str) -> dict:
    """Extract JSON tool call from model output. Raises ValueError if not found."""
    clean = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    try:
        obj = json.loads(clean)
        if "tool" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    for m in re.finditer(r"\{[^{}]*\"tool\"[^{}]*\}", clean):
        try:
            obj = json.loads(m.group(0))
            if "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not parse tool call from model output: {raw[:200]}")


class TaskAgent:
    def __init__(
        self,
        model: str = EXECUTOR_MODEL,
        require_confirmation: bool = True,
    ):
        self.model = model
        self.require_confirmation = require_confirmation

    def execute_step(self, bb: Blackboard, step_index: int) -> dict:
        """
        Execute one step from bb.plan[step_index].

        Returns dict with keys:
            success: bool
            tool_used: str
            output: str (on success)
            error: str (on failure)
            requires_confirmation: bool (when blocked)
            risk: ActionRisk (when blocked)
        """
        step = bb.plan[step_index]
        system = _SYSTEM_PROMPT
        user = _USER_TEMPLATE.format(
            context=bb.context_summary(),
            step=step,
        )

        raw, _ = _call_ollama(system, user, self.model)

        try:
            tool_call = _extract_tool_call(raw)
        except ValueError as e:
            return {"success": False, "tool_used": "", "error": f"JSON parse error: {e}"}

        tool_name = tool_call.get("tool", "")
        args = tool_call.get("args", {})

        risk = classify_action(tool_name, args)
        if self.require_confirmation and risk == ActionRisk.IRREVERSIBLE:
            return {
                "success": False,
                "tool_used": tool_name,
                "requires_confirmation": True,
                "risk": risk,
                "pending_call": tool_call,
                "error": f"Action requires confirmation: {tool_name}({args})",
            }

        result = dispatch(tool_call)

        if "error" in result:
            return {
                "success": False,
                "tool_used": tool_name,
                "error": result["error"],
                "requires_confirmation": False,
                "risk": risk,
            }

        return {
            "success": True,
            "tool_used": tool_name,
            "output": str(result)[:500],
            "requires_confirmation": False,
            "risk": risk,
        }
