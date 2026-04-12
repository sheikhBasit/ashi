# Autonomous Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ASHI a real autonomous agent loop so it can take a goal, break it into steps, execute each step using existing tools, observe results, and loop until done — without the user babysitting it.

**Architecture:** A two-tier Python system: `HostAgent` decomposes the user's goal into a step plan using `deepseek-r1:8b`, then a `TaskAgent` executes each step one at a time using `qwen3:4b` via the existing `tool_dispatch.py`. A `Blackboard` holds shared state between steps. Every irreversible action (file delete, network call) requires explicit confirmation before execution. The loop runs via a new `run_agent` function exposed through the existing Tauri IPC bridge.

**Tech Stack:** Python asyncio, `smolagents` (HuggingFace, Ollama-native), existing `tool_dispatch.py`, existing `tcu.py`, existing `run_skill.py`, Tauri IPC (new command `run_agent`), React (new `AgentPanel.tsx`)

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `functions/blackboard.py` | Create | Shared state dict for a single agent run |
| `functions/host_agent.py` | Create | Decomposes goal into steps via deepseek-r1:8b |
| `functions/task_agent.py` | Create | Executes one step via qwen3:4b + tool_dispatch |
| `functions/agent_runner.py` | Create | Orchestrates HostAgent → TaskAgent loop, manages TCU lifecycle |
| `functions/action_classifier.py` | Create | Classifies each tool call as reversible/irreversible |
| `functions/tool_dispatch.py` | Modify | Register `run_agent` tool so agents can spawn sub-tasks |
| `app/src-tauri/src/lib.rs` | Modify | Add `run_agent` Tauri command |
| `app/src/api.ts` | Modify | Add `runAgent()` IPC call |
| `app/src/types.ts` | Modify | Add `AgentRun`, `AgentStep` types |
| `app/src/components/AgentPanel.tsx` | Create | UI to submit goals, watch steps live |
| `app/src/App.tsx` | Modify | Add `agent` panel to routing + Sidebar |
| `app/src/components/Sidebar.tsx` | Modify | Add Agent nav item |
| `tests/test_blackboard.py` | Create | Unit tests for Blackboard |
| `tests/test_host_agent.py` | Create | Unit tests for HostAgent planning |
| `tests/test_task_agent.py` | Create | Unit tests for TaskAgent execution |
| `tests/test_action_classifier.py` | Create | Unit tests for action classification |
| `tests/test_agent_runner.py` | Create | Integration test for full loop |

---

## Task 1: Blackboard

**Files:**
- Create: `functions/blackboard.py`
- Create: `tests/test_blackboard.py`

The Blackboard is the shared state dict for one agent run. It stores the goal, step plan, step results, and final output. All agents read/write through it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blackboard.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from blackboard import Blackboard

def test_blackboard_stores_goal():
    bb = Blackboard(goal="research ASHI")
    assert bb.goal == "research ASHI"

def test_blackboard_set_plan():
    bb = Blackboard(goal="test")
    bb.set_plan(["step 1", "step 2"])
    assert bb.plan == ["step 1", "step 2"]
    assert bb.total_steps == 2

def test_blackboard_record_step_result():
    bb = Blackboard(goal="test")
    bb.set_plan(["do thing"])
    bb.record_result(0, "thing done", success=True)
    assert bb.results[0]["output"] == "thing done"
    assert bb.results[0]["success"] is True

def test_blackboard_step_budget():
    bb = Blackboard(goal="test", max_steps=5)
    assert bb.steps_remaining == 5
    bb.set_plan(["a", "b", "c"])
    bb.record_result(0, "ok", success=True)
    assert bb.steps_remaining == 4

def test_blackboard_is_done_when_all_steps_complete():
    bb = Blackboard(goal="test")
    bb.set_plan(["a", "b"])
    bb.record_result(0, "ok", success=True)
    bb.record_result(1, "ok", success=True)
    assert bb.is_done is True

def test_blackboard_to_dict_roundtrip():
    bb = Blackboard(goal="test")
    bb.set_plan(["a"])
    bb.record_result(0, "out", success=True)
    d = bb.to_dict()
    assert d["goal"] == "test"
    assert len(d["results"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_blackboard.py -v
```
Expected: `ModuleNotFoundError: No module named 'blackboard'`

- [ ] **Step 3: Implement Blackboard**

```python
# functions/blackboard.py
"""
Blackboard — shared state for one agent run.
All agents read/write through this object. Serializable to dict for TCU storage.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Blackboard:
    goal: str
    max_steps: int = 20
    plan: list[str] = field(default_factory=list)
    results: dict[int, dict] = field(default_factory=dict)
    current_step_index: int = 0
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    final_output: Optional[str] = None

    def set_plan(self, steps: list[str]) -> None:
        self.plan = steps
        self.current_step_index = 0

    @property
    def total_steps(self) -> int:
        return len(self.plan)

    @property
    def steps_remaining(self) -> int:
        completed = len(self.results)
        return self.max_steps - completed

    @property
    def is_done(self) -> bool:
        if not self.plan:
            return False
        return len(self.results) >= len(self.plan)

    @property
    def has_budget(self) -> bool:
        return self.steps_remaining > 0

    def record_result(self, step_index: int, output: str, success: bool) -> None:
        self.results[step_index] = {
            "step": self.plan[step_index] if step_index < len(self.plan) else "unknown",
            "output": output,
            "success": success,
            "recorded_at": datetime.now().isoformat(),
        }
        self.current_step_index = step_index + 1

    def context_summary(self) -> str:
        """Compact summary of completed work for injection into next prompt."""
        if not self.results:
            return "No steps completed yet."
        lines = [f"Goal: {self.goal}", "Completed steps:"]
        for i, r in sorted(self.results.items()):
            status = "✓" if r["success"] else "✗"
            # truncate long outputs to prevent context overflow
            out = r["output"][:200] + "..." if len(r["output"]) > 200 else r["output"]
            lines.append(f"  {status} Step {i+1}: {r['step']}\n     → {out}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "max_steps": self.max_steps,
            "plan": self.plan,
            "results": {str(k): v for k, v in self.results.items()},
            "current_step_index": self.current_step_index,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "final_output": self.final_output,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_blackboard.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add functions/blackboard.py tests/test_blackboard.py
git commit -m "feat(agent): add Blackboard shared state for agent runs"
```

---

## Task 2: Action Classifier

**Files:**
- Create: `functions/action_classifier.py`
- Create: `tests/test_action_classifier.py`

Every tool call is classified as `reversible` or `irreversible` before execution. Irreversible actions must be confirmed. This is the safety gate.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_action_classifier.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from action_classifier import classify_action, ActionRisk

def test_shell_delete_is_irreversible():
    risk = classify_action("run_shell", {"command": "rm -rf /tmp/test"})
    assert risk == ActionRisk.IRREVERSIBLE

def test_shell_read_is_reversible():
    risk = classify_action("run_shell", {"command": "ls /home"})
    assert risk == ActionRisk.REVERSIBLE

def test_search_wiki_is_reversible():
    risk = classify_action("search_wiki", {"query": "ASHI"})
    assert risk == ActionRisk.REVERSIBLE

def test_ingest_source_is_irreversible():
    risk = classify_action("ingest_source", {"url": "http://example.com"})
    assert risk == ActionRisk.IRREVERSIBLE

def test_update_entity_is_irreversible():
    risk = classify_action("update_entity", {"entity_name": "ASHI"})
    assert risk == ActionRisk.IRREVERSIBLE

def test_run_skill_is_reversible():
    risk = classify_action("run_skill", {"skill_name": "research"})
    assert risk == ActionRisk.REVERSIBLE

def test_unknown_tool_defaults_to_irreversible():
    risk = classify_action("unknown_future_tool", {})
    assert risk == ActionRisk.IRREVERSIBLE
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_action_classifier.py -v
```
Expected: `ModuleNotFoundError: No module named 'action_classifier'`

- [ ] **Step 3: Implement ActionClassifier**

```python
# functions/action_classifier.py
"""
Action classifier — determines if a tool call is safe to execute without confirmation.

REVERSIBLE: read-only, no external side effects, undoable
IRREVERSIBLE: writes data, deletes files, sends network requests, modifies system state

Unknown tools default to IRREVERSIBLE (safe default).
"""
from enum import Enum
import re


class ActionRisk(str, Enum):
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


# Tools that are always safe (read-only)
_REVERSIBLE_TOOLS = {
    "search_wiki",
    "lint_wiki",
    "run_skill",
    "list_skills",
    "get_skill_info",
    "ide_list_extensions",
    "ide_status",
}

# Tools that are always irreversible (write/delete/network)
_IRREVERSIBLE_TOOLS = {
    "ingest_source",
    "update_entity",
    "review_task",
    "create_tcu",
    "append_wiki_log",
    "ide_route",
    "ide_open",
    "ide_switch_model",
    "ide_toggle_copilot",
    "ide_install_extension",
    "ide_smart_open",
    "opencode",
    "emit_metric",
}

# Shell commands that are read-only (prefix/exact match)
_SAFE_SHELL_PREFIXES = (
    "ls ", "ls\n", "ls",
    "cat ", "head ", "tail ",
    "grep ", "find ", "du ", "df ",
    "ps ", "top ", "htop",
    "pwd", "echo ", "which ", "type ",
    "env", "printenv",
    "git log", "git status", "git diff", "git show",
    "python ", "python3 ",
)

# Shell patterns that are always irreversible
_DANGEROUS_SHELL_PATTERNS = re.compile(
    r"\brm\b|\bmv\b|\bcp\b|\bchmod\b|\bchown\b|"
    r"\bsudo\b|\bapt\b|\bpip\b|\bnpm\b|\byarn\b|"
    r"\bcurl\b|\bwget\b|\bssh\b|\bscp\b|\brsync\b|"
    r">\s*[^\s]|>>\s*[^\s]|\|\s*tee\b"
)


def classify_action(tool_name: str, args: dict) -> ActionRisk:
    """
    Classify a tool call as REVERSIBLE or IRREVERSIBLE.

    Args:
        tool_name: Name of the tool to call
        args: Arguments dict for the tool call

    Returns:
        ActionRisk.REVERSIBLE or ActionRisk.IRREVERSIBLE
    """
    if tool_name in _REVERSIBLE_TOOLS:
        return ActionRisk.REVERSIBLE

    if tool_name in _IRREVERSIBLE_TOOLS:
        return ActionRisk.IRREVERSIBLE

    if tool_name == "run_shell":
        command = args.get("command", "").strip()
        if _DANGEROUS_SHELL_PATTERNS.search(command):
            return ActionRisk.IRREVERSIBLE
        if any(command.startswith(p) for p in _SAFE_SHELL_PREFIXES):
            return ActionRisk.REVERSIBLE
        # unknown shell command — be safe
        return ActionRisk.IRREVERSIBLE

    # unknown tool — default safe
    return ActionRisk.IRREVERSIBLE
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_action_classifier.py -v
```
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add functions/action_classifier.py tests/test_action_classifier.py
git commit -m "feat(agent): add action classifier for safety gate"
```

---

## Task 3: HostAgent

**Files:**
- Create: `functions/host_agent.py`
- Create: `tests/test_host_agent.py`

HostAgent receives the user's goal and returns a numbered list of concrete steps. Uses `deepseek-r1:8b` (the planner model). Returns a list of step strings that go into the Blackboard.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_host_agent.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch
from host_agent import HostAgent
from blackboard import Blackboard

def _mock_ollama_response(steps_text: str):
    """Helper: mock _call_ollama to return a fake step list."""
    return patch(
        "host_agent._call_ollama",
        return_value=(steps_text, 100)
    )

def test_host_agent_returns_step_list():
    bb = Blackboard(goal="research ASHI and write a summary")
    agent = HostAgent()
    fake_response = "1. Search wiki for ASHI\n2. Summarize findings\n3. Write output to file"
    with _mock_ollama_response(fake_response):
        steps = agent.plan(bb)
    assert len(steps) == 3
    assert "Search wiki" in steps[0]

def test_host_agent_strips_numbering():
    bb = Blackboard(goal="do something")
    agent = HostAgent()
    fake_response = "1. Step one\n2. Step two\n3. Step three"
    with _mock_ollama_response(fake_response):
        steps = agent.plan(bb)
    # Steps should not start with "1." etc
    assert not steps[0].startswith("1.")
    assert not steps[1].startswith("2.")

def test_host_agent_caps_steps_at_max():
    bb = Blackboard(goal="do ten things", max_steps=3)
    agent = HostAgent()
    # Model returns 10 steps but max_steps=3 so only 3 should be returned
    fake_response = "\n".join(f"{i+1}. Step {i+1}" for i in range(10))
    with _mock_ollama_response(fake_response):
        steps = agent.plan(bb)
    assert len(steps) <= 3

def test_host_agent_handles_empty_response():
    bb = Blackboard(goal="do something")
    agent = HostAgent()
    with _mock_ollama_response(""):
        steps = agent.plan(bb)
    assert steps == ["Complete the goal: do something"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_host_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'host_agent'`

- [ ] **Step 3: Implement HostAgent**

```python
# functions/host_agent.py
"""
HostAgent — decomposes a user goal into a concrete numbered step plan.
Uses deepseek-r1:8b (the planner model) via Ollama.
"""
import os
import re
import sys

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

from run_skill import _call_with_fallback
from blackboard import Blackboard

PLANNER_MODEL = os.environ.get("ASHI_PLANNER_MODEL", "ashi-planner")

_SYSTEM_PROMPT = """\
You are ASHI's planning agent. You receive a user goal and decompose it into a \
numbered list of concrete, executable steps. Each step must be a single action \
that can be completed with one tool call (search wiki, run shell command, read file, \
write output, etc.).

Rules:
- Return ONLY a numbered list. No explanation, no preamble.
- Each step: one action, one tool.
- Maximum {max_steps} steps.
- Steps must be ordered: information gathering first, then writing/modifying.
- Be specific: "Search wiki for ASHI architecture" not "do research".

Available tools: search_wiki, run_shell, run_skill, ingest_source, update_entity, \
append_wiki_log, list_skills, opencode
"""

_USER_TEMPLATE = """\
Goal: {goal}

Steps completed so far:
{context}

Remaining step budget: {budget}

Write the next {max_steps} steps to complete this goal.
"""


def _call_ollama(system: str, user: str, model: str) -> tuple[str, int]:
    """Thin wrapper so tests can patch it."""
    text, tokens, _ = _call_with_fallback(system, user, model)
    return text, tokens


def _parse_steps(raw: str, max_steps: int) -> list[str]:
    """Extract step strings from numbered list. Caps at max_steps."""
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    steps = []
    for line in lines:
        # strip leading number+dot/paren: "1.", "1)", "1 -", etc.
        clean = re.sub(r"^\d+[.):\-\s]+", "", line).strip()
        if clean:
            steps.append(clean)
    return steps[:max_steps]


class HostAgent:
    def __init__(self, model: str = PLANNER_MODEL):
        self.model = model

    def plan(self, bb: Blackboard) -> list[str]:
        """
        Decompose bb.goal into a list of step strings.
        Writes the plan into bb and returns it.

        Args:
            bb: Blackboard with .goal set

        Returns:
            List of step strings (already written to bb.plan)
        """
        budget = min(bb.max_steps, 10)  # never ask for more than 10 at once
        system = _SYSTEM_PROMPT.format(max_steps=budget)
        user = _USER_TEMPLATE.format(
            goal=bb.goal,
            context=bb.context_summary(),
            budget=bb.steps_remaining,
            max_steps=budget,
        )

        raw, _ = _call_ollama(system, user, self.model)
        steps = _parse_steps(raw, budget)

        if not steps:
            steps = [f"Complete the goal: {bb.goal}"]

        bb.set_plan(steps)
        return steps
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_host_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add functions/host_agent.py tests/test_host_agent.py
git commit -m "feat(agent): add HostAgent for goal decomposition"
```

---

## Task 4: TaskAgent

**Files:**
- Create: `functions/task_agent.py`
- Create: `tests/test_task_agent.py`

TaskAgent receives a single step string and executes it. It uses `qwen3:4b` to pick the right tool + args, then calls `tool_dispatch.dispatch()`. Returns the result.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_task_agent.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch, MagicMock
from task_agent import TaskAgent
from blackboard import Blackboard
from action_classifier import ActionRisk

def _mock_executor(tool_json: str):
    return patch("task_agent._call_ollama", return_value=(tool_json, 50))

def _mock_dispatch(result: dict):
    return patch("task_agent.dispatch", return_value=result)

def test_task_agent_executes_reversible_tool():
    bb = Blackboard(goal="test")
    bb.set_plan(["Search wiki for ASHI"])
    agent = TaskAgent(require_confirmation=False)

    tool_response = '{"tool": "search_wiki", "args": {"query": "ASHI", "wiki_path": "~/Desktop/SecondBrain/wiki", "top_k": 3}}'
    dispatch_result = {"results": [{"snippet": "ASHI is a local AI OS"}]}

    with _mock_executor(tool_response), _mock_dispatch(dispatch_result):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is True
    assert "search_wiki" in result["tool_used"]

def test_task_agent_blocks_irreversible_without_confirmation():
    bb = Blackboard(goal="test")
    bb.set_plan(["Delete all temp files"])
    agent = TaskAgent(require_confirmation=True)

    tool_response = '{"tool": "run_shell", "args": {"command": "rm -rf /tmp/*"}}'

    with _mock_executor(tool_response):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is False
    assert result["requires_confirmation"] is True
    assert result["risk"] == ActionRisk.IRREVERSIBLE

def test_task_agent_handles_invalid_tool_json():
    bb = Blackboard(goal="test")
    bb.set_plan(["Do something"])
    agent = TaskAgent(require_confirmation=False)

    with _mock_executor("not valid json at all"):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is False
    assert "parse" in result["error"].lower() or "json" in result["error"].lower()

def test_task_agent_handles_dispatch_error():
    bb = Blackboard(goal="test")
    bb.set_plan(["Search wiki"])
    agent = TaskAgent(require_confirmation=False)

    tool_response = '{"tool": "search_wiki", "args": {"query": "test"}}'
    dispatch_error = {"error": "wiki not found", "tool": "search_wiki"}

    with _mock_executor(tool_response), _mock_dispatch(dispatch_error):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is False
    assert "wiki not found" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_task_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'task_agent'`

- [ ] **Step 3: Implement TaskAgent**

```python
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
    # strip markdown fences if present
    clean = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    # try full string first
    try:
        obj = json.loads(clean)
        if "tool" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # find first {...} block containing "tool"
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

        # safety gate
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

        output = json.dumps(result) if not isinstance(result.get("result"), str) else result["result"]
        return {
            "success": True,
            "tool_used": tool_name,
            "output": str(result)[:500],  # cap output length
            "requires_confirmation": False,
            "risk": risk,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_task_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add functions/task_agent.py tests/test_task_agent.py
git commit -m "feat(agent): add TaskAgent for single-step execution with safety gate"
```

---

## Task 5: AgentRunner

**Files:**
- Create: `functions/agent_runner.py`
- Create: `tests/test_agent_runner.py`

AgentRunner is the orchestrator. It creates a TCU, runs HostAgent to get the plan, then loops through steps with TaskAgent. Handles step budget, convergence detection, and TCU lifecycle.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_runner.py
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch, MagicMock
from agent_runner import run_agent, AgentResult

def _mock_plan(steps):
    return patch("agent_runner.HostAgent.plan", return_value=steps)

def _mock_step(result_dict):
    return patch("agent_runner.TaskAgent.execute_step", return_value=result_dict)

def test_run_agent_returns_agent_result():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["search wiki"]), \
             _mock_step({"success": True, "tool_used": "search_wiki", "output": "found stuff"}):
            result = run_agent("find ASHI info", tasks_path=tmpdir, require_confirmation=False)

    assert isinstance(result, AgentResult)
    assert result.goal == "find ASHI info"
    assert result.steps_completed >= 1

def test_run_agent_stops_at_budget():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["step 1", "step 2", "step 3", "step 4", "step 5"]), \
             _mock_step({"success": True, "tool_used": "search_wiki", "output": "ok"}):
            result = run_agent("do many things", max_steps=2, tasks_path=tmpdir, require_confirmation=False)

    assert result.steps_completed <= 2

def test_run_agent_pauses_on_confirmation_required():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["delete files"]), \
             _mock_step({
                 "success": False,
                 "tool_used": "run_shell",
                 "requires_confirmation": True,
                 "risk": "irreversible",
                 "pending_call": {"tool": "run_shell", "args": {"command": "rm -rf /tmp/x"}},
                 "error": "Action requires confirmation",
             }):
            result = run_agent("delete files", tasks_path=tmpdir, require_confirmation=True)

    assert result.status == "awaiting_confirmation"
    assert result.pending_confirmation is not None

def test_run_agent_detects_convergence():
    """If N consecutive steps fail, agent stops."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["step1", "step2", "step3"]), \
             _mock_step({"success": False, "tool_used": "run_shell", "error": "failed"}):
            result = run_agent("do stuff", tasks_path=tmpdir, require_confirmation=False, max_consecutive_failures=2)

    assert result.status in ("failed", "done")
    assert result.steps_completed <= 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_agent_runner.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent_runner'`

- [ ] **Step 3: Implement AgentRunner**

```python
# functions/agent_runner.py
"""
AgentRunner — orchestrates the full HostAgent → TaskAgent loop.
Creates and manages a TCU for the run. Handles budget, safety, convergence.
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

from blackboard import Blackboard
from host_agent import HostAgent
from task_agent import TaskAgent

_TASKS_PATH = os.path.expanduser("~/Desktop/SecondBrain/tasks")

try:
    from tcu import TCU
    _TCU_AVAILABLE = True
except ImportError:
    _TCU_AVAILABLE = False


@dataclass
class AgentResult:
    goal: str
    status: str  # "done" | "failed" | "awaiting_confirmation" | "budget_exceeded"
    steps_completed: int
    steps_total: int
    outputs: list[dict] = field(default_factory=list)
    final_output: str = ""
    tcu_id: Optional[str] = None
    pending_confirmation: Optional[dict] = None  # set when awaiting_confirmation
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None


def run_agent(
    goal: str,
    max_steps: int = 10,
    require_confirmation: bool = True,
    max_consecutive_failures: int = 3,
    tasks_path: str = _TASKS_PATH,
    project: str = "ashi",
) -> AgentResult:
    """
    Run the full agent loop for a goal.

    Args:
        goal: What to accomplish
        max_steps: Hard cap on total steps
        require_confirmation: Whether to pause on irreversible actions
        max_consecutive_failures: Stop if this many steps fail in a row
        tasks_path: Where to write TCU files
        project: TCU project label

    Returns:
        AgentResult with full run state
    """
    bb = Blackboard(goal=goal, max_steps=max_steps)
    tcu = None
    tcu_id = None

    if _TCU_AVAILABLE:
        try:
            tcu = TCU.create(goal, project, tasks_path)
            tcu_id = tcu._data["id"]
        except Exception:
            pass  # TCU is optional — don't fail the run

    host = HostAgent()
    task = TaskAgent(require_confirmation=require_confirmation)

    # Phase 1: planning
    try:
        steps = host.plan(bb)
    except Exception as e:
        return AgentResult(
            goal=goal,
            status="failed",
            steps_completed=0,
            steps_total=0,
            error=f"Planning failed: {e}",
            tcu_id=tcu_id,
            finished_at=datetime.now().isoformat(),
        )

    if tcu:
        try:
            tcu.start_step(0, f"Planning: {goal[:60]}")
            tcu.complete_step(0, f"{len(steps)} steps planned")
        except Exception:
            pass

    # Phase 2: execution loop
    outputs = []
    consecutive_failures = 0

    for i, step in enumerate(bb.plan):
        if not bb.has_budget:
            return AgentResult(
                goal=goal,
                status="budget_exceeded",
                steps_completed=i,
                steps_total=bb.total_steps,
                outputs=outputs,
                tcu_id=tcu_id,
                finished_at=datetime.now().isoformat(),
            )

        if tcu:
            try:
                tcu.start_step(i + 1, step[:80])
            except Exception:
                pass

        step_result = task.execute_step(bb, i)
        outputs.append({"step": step, **step_result})

        # paused — waiting for user confirmation
        if step_result.get("requires_confirmation"):
            return AgentResult(
                goal=goal,
                status="awaiting_confirmation",
                steps_completed=i,
                steps_total=bb.total_steps,
                outputs=outputs,
                pending_confirmation={
                    "step_index": i,
                    "step": step,
                    "pending_call": step_result.get("pending_call"),
                },
                tcu_id=tcu_id,
                finished_at=datetime.now().isoformat(),
            )

        if step_result["success"]:
            consecutive_failures = 0
            bb.record_result(i, step_result.get("output", ""), success=True)
            if tcu:
                try:
                    tcu.complete_step(i + 1, step_result.get("output", "")[:200])
                except Exception:
                    pass
        else:
            consecutive_failures += 1
            bb.record_result(i, step_result.get("error", "unknown error"), success=False)
            if tcu:
                try:
                    tcu.complete_step(i + 1, f"FAILED: {step_result.get('error', '')[:200]}")
                except Exception:
                    pass
            if consecutive_failures >= max_consecutive_failures:
                return AgentResult(
                    goal=goal,
                    status="failed",
                    steps_completed=i + 1,
                    steps_total=bb.total_steps,
                    outputs=outputs,
                    error=f"Stopped after {consecutive_failures} consecutive failures",
                    tcu_id=tcu_id,
                    finished_at=datetime.now().isoformat(),
                )

    # build final output summary
    successful = [o for o in outputs if o.get("success")]
    final_output = bb.context_summary()

    if tcu:
        try:
            tcu.mark_done(judge_score=len(successful) / max(len(outputs), 1))
        except Exception:
            pass

    return AgentResult(
        goal=goal,
        status="done",
        steps_completed=len(outputs),
        steps_total=bb.total_steps,
        outputs=outputs,
        final_output=final_output,
        tcu_id=tcu_id,
        finished_at=datetime.now().isoformat(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_agent_runner.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Run all agent tests together**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/python -m pytest tests/test_blackboard.py tests/test_action_classifier.py tests/test_host_agent.py tests/test_task_agent.py tests/test_agent_runner.py -v
```
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add functions/agent_runner.py tests/test_agent_runner.py
git commit -m "feat(agent): add AgentRunner orchestrator with budget and convergence detection"
```

---

## Task 6: Wire Into Tauri IPC

**Files:**
- Modify: `app/src-tauri/src/lib.rs`
- Modify: `app/src/api.ts`
- Modify: `app/src/types.ts`

Add a `run_agent` Tauri command so the frontend can submit goals and stream progress.

- [ ] **Step 1: Add `AgentRun` and `AgentStep` types to `types.ts`**

Open `app/src/types.ts` and add at the end:

```typescript
export interface AgentStep {
  step: string;
  success: boolean;
  tool_used: string;
  output?: string;
  error?: string;
  requires_confirmation?: boolean;
  risk?: string;
  pending_call?: Record<string, unknown>;
}

export interface AgentRun {
  goal: string;
  status: "done" | "failed" | "awaiting_confirmation" | "budget_exceeded";
  steps_completed: number;
  steps_total: number;
  outputs: AgentStep[];
  final_output: string;
  tcu_id: string | null;
  pending_confirmation: {
    step_index: number;
    step: string;
    pending_call: Record<string, unknown> | null;
  } | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}
```

- [ ] **Step 2: Add `run_agent` Tauri command to `lib.rs`**

Open `app/src-tauri/src/lib.rs`. Find the `pub fn run()` function at the bottom. Before it, add this new command after the existing `get_monitor_stats` function:

```rust
/// Run the autonomous agent loop for a goal.
/// Returns JSON AgentResult.
#[tauri::command]
async fn run_agent(
    goal: String,
    max_steps: Option<u32>,
    require_confirmation: Option<bool>,
) -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/workspace/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/workspace/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);
    let steps = max_steps.unwrap_or(10);
    let confirm = require_confirmation.unwrap_or(true);

    let script = format!(
        r#"
import sys, json
sys.path.insert(0, '{ashi_dir}/functions')
from agent_runner import run_agent
import dataclasses
result = run_agent(
    goal={goal_repr},
    max_steps={steps},
    require_confirmation={confirm_py},
    tasks_path='{ashi_dir}/../SecondBrain/tasks',
)
# dataclass → dict
d = dataclasses.asdict(result)
print(json.dumps(d))
"#,
        ashi_dir = ashi_dir,
        goal_repr = serde_json::to_string(&goal).unwrap_or_default(),
        steps = steps,
        confirm_py = if confirm { "True" } else { "False" },
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}
```

Then update the `invoke_handler` in `pub fn run()`:

```rust
.invoke_handler(tauri::generate_handler![
    run_ashi,
    run_skill,
    dispatch_tool,
    search_wiki,
    read_wiki_file,
    list_skills,
    list_tcus,
    run_shell,
    get_monitor_stats,
    run_agent,
])
```

- [ ] **Step 3: Add `runAgent()` to `api.ts`**

Open `app/src/api.ts`. Add after the existing `dispatchTool` function:

```typescript
export async function runAgent(
  goal: string,
  maxSteps = 10,
  requireConfirmation = true,
): Promise<AgentRun> {
  const raw = await call<string>("run_agent", {
    goal,
    maxSteps,
    requireConfirmation,
  });
  return JSON.parse(raw);
}
```

Also add `AgentRun` to the import at the top of `api.ts`:

```typescript
import type { WikiResult, TCU, Skill, MonitorData, AgentRun } from "./types";
```

Also add a mock for `run_agent` in the `mockCall` function:

```typescript
run_agent: JSON.stringify({
  goal: "mock goal",
  status: "done",
  steps_completed: 2,
  steps_total: 2,
  outputs: [
    { step: "Search wiki", success: true, tool_used: "search_wiki", output: "Found ASHI docs" },
    { step: "Summarize findings", success: true, tool_used: "run_skill", output: "ASHI is a local AI OS" },
  ],
  final_output: "Goal completed successfully.",
  tcu_id: "mock_agent_001",
  pending_confirmation: null,
  error: null,
  started_at: new Date().toISOString(),
  finished_at: new Date().toISOString(),
} as AgentRun),
```

- [ ] **Step 4: Build Tauri to verify no compile errors**

```bash
cd /home/basitdev/workspace/ashi/app
npm run build 2>&1 | tail -20
```
Expected: Build succeeds (or TypeScript errors only — Rust compile errors would be a problem)

- [ ] **Step 5: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add app/src/types.ts app/src/api.ts app/src-tauri/src/lib.rs
git commit -m "feat(agent): wire run_agent through Tauri IPC bridge"
```

---

## Task 7: AgentPanel UI

**Files:**
- Create: `app/src/components/AgentPanel.tsx`
- Modify: `app/src/App.tsx`
- Modify: `app/src/components/Sidebar.tsx`

A panel where you type a goal, hit Run, and watch steps execute live. Shows step status, tool used, output, and pauses for confirmation on irreversible actions.

- [ ] **Step 1: Create `AgentPanel.tsx`**

```tsx
// app/src/components/AgentPanel.tsx
import { useState } from "react";
import { Play, CheckCircle, XCircle, AlertTriangle, Loader } from "lucide-react";
import { runAgent, dispatchTool } from "../api";
import type { AgentRun, AgentStep } from "../types";

export default function AgentPanel() {
  const [goal, setGoal] = useState("");
  const [maxSteps, setMaxSteps] = useState(10);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AgentRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    if (!goal.trim() || running) return;
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const r = await runAgent(goal.trim(), maxSteps, true);
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function handleConfirm() {
    if (!result?.pending_confirmation) return;
    const { step_index, pending_call } = result.pending_confirmation;
    if (!pending_call) return;

    setRunning(true);
    try {
      // execute the confirmed tool call
      const toolResult = await dispatchTool(
        pending_call.tool as string,
        pending_call.args as Record<string, unknown>,
      );
      // then resume the rest of the agent run from next step
      const resumed = await runAgent(result.goal, maxSteps, true);
      setResult(resumed);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  function handleDeny() {
    if (!result) return;
    setResult({ ...result, status: "failed", error: "Action denied by user." });
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: 16 }}>
      {/* Header */}
      <div style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11, marginBottom: 16 }}>
        AGENT — AUTONOMOUS TASK RUNNER
      </div>

      {/* Goal input */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleRun()}
          placeholder="Enter a goal — e.g. 'Research ASHI and write a wiki summary'"
          style={{
            flex: 1,
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
            padding: "8px 10px",
            fontSize: 13,
            outline: "none",
            fontFamily: "inherit",
          }}
        />
        <input
          type="number"
          value={maxSteps}
          onChange={(e) => setMaxSteps(Number(e.target.value))}
          min={1}
          max={20}
          title="Max steps"
          style={{
            width: 52,
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text-muted)",
            padding: "8px 6px",
            fontSize: 12,
            textAlign: "center",
            outline: "none",
          }}
        />
        <button
          onClick={handleRun}
          disabled={running || !goal.trim()}
          style={{
            background: "var(--accent)",
            border: "none",
            borderRadius: 4,
            padding: "0 14px",
            cursor: running ? "not-allowed" : "pointer",
            opacity: running ? 0.5 : 1,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
          }}
        >
          {running ? <Loader size={13} className="spin" /> : <Play size={13} />}
          {running ? "Running…" : "Run"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          background: "var(--red-dim, #2a1515)",
          border: "1px solid var(--red, #f87171)",
          borderRadius: 6,
          padding: "10px 12px",
          color: "var(--red, #f87171)",
          fontSize: 12,
          marginBottom: 12,
        }}>
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div style={{ flex: 1, overflowY: "auto" }}>
          {/* Status bar */}
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 12,
            padding: "8px 10px",
            background: "var(--surface2)",
            borderRadius: 6,
            border: "1px solid var(--border)",
          }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {result.steps_completed}/{result.steps_total} steps
              {result.tcu_id && <span style={{ marginLeft: 8, color: "var(--accent)", fontSize: 10 }}>TCU: {result.tcu_id}</span>}
            </span>
            <StatusBadge status={result.status} />
          </div>

          {/* Confirmation prompt */}
          {result.status === "awaiting_confirmation" && result.pending_confirmation && (
            <div style={{
              background: "var(--yellow-dim, #2a2200)",
              border: "1px solid var(--yellow, #fbbf24)",
              borderRadius: 6,
              padding: "12px 14px",
              marginBottom: 12,
            }}>
              <div style={{ color: "var(--yellow, #fbbf24)", fontWeight: 600, fontSize: 12, marginBottom: 6 }}>
                <AlertTriangle size={12} style={{ marginRight: 6 }} />
                Confirmation required — irreversible action
              </div>
              <div style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text)", marginBottom: 10 }}>
                {JSON.stringify(result.pending_confirmation.pending_call, null, 2)}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={handleConfirm} style={{ background: "var(--yellow, #fbbf24)", border: "none", borderRadius: 4, padding: "5px 12px", cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#000" }}>
                  Allow
                </button>
                <button onClick={handleDeny} style={{ background: "transparent", border: "1px solid var(--border)", borderRadius: 4, padding: "5px 12px", cursor: "pointer", fontSize: 12, color: "var(--text-muted)" }}>
                  Deny
                </button>
              </div>
            </div>
          )}

          {/* Steps */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {result.outputs.map((step, i) => (
              <StepCard key={i} step={step} index={i} />
            ))}
          </div>

          {/* Final output */}
          {result.final_output && (
            <div style={{
              marginTop: 16,
              padding: "12px 14px",
              background: "var(--surface2)",
              border: "1px solid var(--accent)",
              borderRadius: 6,
            }}>
              <div style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11, marginBottom: 8 }}>FINAL OUTPUT</div>
              <pre style={{ fontSize: 12, color: "var(--text)", whiteSpace: "pre-wrap", margin: 0, lineHeight: 1.6 }}>
                {result.final_output}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: AgentRun["status"] }) {
  const config = {
    done: { color: "var(--green)", label: "Done" },
    failed: { color: "var(--red, #f87171)", label: "Failed" },
    awaiting_confirmation: { color: "var(--yellow, #fbbf24)", label: "Waiting for approval" },
    budget_exceeded: { color: "var(--text-muted)", label: "Budget exceeded" },
  }[status] ?? { color: "var(--text-muted)", label: status };

  return (
    <span style={{ fontSize: 11, color: config.color, fontWeight: 600 }}>
      {config.label}
    </span>
  );
}

function StepCard({ step, index }: { step: AgentStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = step.success ? CheckCircle : XCircle;
  const iconColor = step.success ? "var(--green)" : "var(--red, #f87171)";

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      style={{
        cursor: "pointer",
        background: "var(--surface2)",
        border: "1px solid var(--border)",
        borderRadius: 6,
        padding: "10px 12px",
        userSelect: "none",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={13} color={iconColor} />
        <span style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 20 }}>{index + 1}.</span>
        <span style={{ flex: 1, fontSize: 12, color: "var(--text)" }}>{step.step}</span>
        {step.tool_used && (
          <span style={{ fontSize: 10, color: "var(--accent)", fontFamily: "monospace" }}>
            {step.tool_used}
          </span>
        )}
      </div>
      {expanded && (step.output || step.error) && (
        <pre style={{
          marginTop: 8,
          fontSize: 11,
          color: step.success ? "var(--text-muted)" : "var(--red, #f87171)",
          whiteSpace: "pre-wrap",
          fontFamily: "monospace",
          borderTop: "1px solid var(--border)",
          paddingTop: 8,
        }}>
          {step.output ?? step.error}
        </pre>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add `agent` panel to `App.tsx`**

Open `app/src/App.tsx`. Add the import at the top:

```typescript
import AgentPanel from "./components/AgentPanel";
```

In the `Panel` type import (from `./types`), it's already `Panel = "pipeline" | "wiki" | "tasks" | "logs" | "terminal" | "monitor"`. Add `"agent"` to that union in `types.ts`:

```typescript
export type Panel = "pipeline" | "wiki" | "tasks" | "logs" | "terminal" | "monitor" | "agent";
```

In `App.tsx`, add inside the `<main>` block after the existing panels:

```tsx
{panel === "agent" && <AgentPanel />}
```

- [ ] **Step 3: Add Agent to Sidebar**

Open `app/src/components/Sidebar.tsx`. Find where the nav items are defined. Add an Agent entry. Look for the array or list of items and add:

```typescript
{ id: "agent", label: "AGENT", icon: Bot }
```

Add `Bot` to the lucide-react import at the top of `Sidebar.tsx`.

- [ ] **Step 4: Build to verify no TypeScript errors**

```bash
cd /home/basitdev/workspace/ashi/app
npm run build 2>&1 | grep -E "error|Error" | head -20
```
Expected: No TypeScript errors

- [ ] **Step 5: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add app/src/components/AgentPanel.tsx app/src/App.tsx app/src/components/Sidebar.tsx app/src/types.ts
git commit -m "feat(agent): add AgentPanel UI with step-by-step view and confirmation gate"
```

---

## Task 8: smolagents Integration (Optional Enhancement)

**Files:**
- Modify: `requirements.txt`
- Modify: `functions/task_agent.py`

Replace the raw Ollama call in TaskAgent with smolagents for better tool-calling reliability with local models.

- [ ] **Step 1: Install smolagents**

```bash
cd /home/basitdev/workspace/ashi
.venv/bin/pip install smolagents[litellm]
```

- [ ] **Step 2: Add to requirements.txt**

Open `requirements.txt` and add:

```
smolagents[litellm]>=1.0.0
```

- [ ] **Step 3: Add `smolagents`-backed executor to `task_agent.py`**

At the bottom of `functions/task_agent.py`, add:

```python
def _build_smolagent_executor(model_name: str):
    """
    Build a smolagents CodeAgent pointed at local Ollama.
    Returns None if smolagents not installed.
    """
    try:
        from smolagents import CodeAgent, LiteLLMModel
        from tool_dispatch import TOOL_REGISTRY

        lm = LiteLLMModel(
            model_id=f"ollama/{model_name}",
            api_base="http://localhost:11434",
        )

        # wrap each tool_dispatch function as a smolagents tool
        from smolagents import tool as smolagent_tool
        smol_tools = []
        for name, fn in list(TOOL_REGISTRY.items())[:8]:  # limit to 8 tools
            wrapped = smolagent_tool(fn)
            smol_tools.append(wrapped)

        return CodeAgent(tools=smol_tools, model=lm)
    except ImportError:
        return None
```

- [ ] **Step 4: Commit**

```bash
cd /home/basitdev/workspace/ashi
git add requirements.txt functions/task_agent.py
git commit -m "feat(agent): add smolagents integration for improved tool-calling reliability"
```

---

## Self-Review

**Spec coverage:**
- ✓ HostAgent (goal decomposition via deepseek-r1:8b) — Task 3
- ✓ TaskAgent (step execution via qwen3:4b + tool_dispatch) — Task 4
- ✓ Blackboard (shared state) — Task 1
- ✓ Safety gate / action classifier — Task 2
- ✓ Step budget visible to model — Blackboard.steps_remaining in prompt
- ✓ Irreversible action confirmation — TaskAgent + AgentPanel confirmation UI
- ✓ Convergence detection (consecutive failures) — AgentRunner Task 5
- ✓ TCU lifecycle — AgentRunner creates/updates TCU
- ✓ Tauri IPC — Task 6
- ✓ UI panel — Task 7

**Placeholder scan:** None found. All steps have complete code.

**Type consistency check:**
- `AgentRun` defined in `types.ts` Task 6 Step 1, used in `AgentPanel.tsx` Task 7 Step 1 ✓
- `AgentStep` defined in `types.ts` Task 6 Step 1, used in `AgentPanel.tsx` ✓
- `AgentResult` dataclass in `agent_runner.py` fields match JSON keys expected in `AgentRun` TypeScript type ✓
- `Blackboard.record_result(step_index, output, success)` — used consistently in `agent_runner.py` ✓
- `TaskAgent.execute_step(bb, step_index)` — signature consistent across test and implementation ✓
- `HostAgent.plan(bb)` — returns `list[str]`, writes to `bb.plan` ✓
