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
        """
        budget = min(bb.max_steps, 10)
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
