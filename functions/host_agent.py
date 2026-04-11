# functions/host_agent.py
"""
HostAgent — multi-brain planner.

Calls 3 fast cloud models in parallel via OpenRouter, merges their step lists
by consensus voting. Steps that appear in 2+ plans are prioritised; remainder
filled from the highest-confidence single plan.

Falls back to local qwen3:4b if OpenRouter is unavailable.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

from run_skill import _call_with_fallback
from blackboard import Blackboard

# Local fallback model (fast, 2.4s on CPU)
LOCAL_FALLBACK_MODEL = os.environ.get("ASHI_PLANNER_FALLBACK", "qwen3:4b")

# Multi-brain: 3 parallel OpenRouter models
# All are free-tier — no billing required
# Using smaller/faster models for low latency planning
BRAIN_MODELS = [
    os.environ.get("ASHI_BRAIN_1", "qwen/qwen3-coder:free"),
    os.environ.get("ASHI_BRAIN_2", "meta-llama/llama-3.3-70b-instruct:free"),
    os.environ.get("ASHI_BRAIN_3", "openai/gpt-oss-20b:free"),
]

_SYSTEM_PROMPT = """\
You are ASHI's planning agent. Decompose the goal into a numbered list of concrete, \
executable steps. Each step = one tool call.

Rules:
- Return ONLY a numbered list. No explanation, no preamble, no markdown.
- Each step: one action, one tool.
- Maximum {max_steps} steps.
- Order: information gathering first, then writing/modifying.
- Be specific: "Search wiki for ASHI architecture" not "do research".

Available tools: search_wiki, run_shell, run_skill, ingest_source, update_entity, \
append_wiki_log, list_skills, opencode
"""

_USER_TEMPLATE = """\
Goal: {goal}

Steps completed so far:
{context}

Remaining step budget: {budget}

Write the next {max_steps} concrete steps.
"""


# ── OpenRouter caller ──────────────────────────────────────────────────────────

def _get_or_keys() -> list[str]:
    keys = [
        os.environ.get("OPENROUTER_KEY_1", ""),
        os.environ.get("OPENROUTER_KEY_2", ""),
        os.environ.get("OPENROUTER_KEY_3", ""),
    ]
    keys = list(dict.fromkeys(k for k in keys if k))
    if not keys:
        single = os.environ.get("OPENROUTER_API_KEY", "")
        if single:
            keys = [single]
    return keys


def _call_openrouter_model(model: str, system: str, user: str) -> Optional[str]:
    """Call one OpenRouter model. Returns text or None on failure."""
    keys = _get_or_keys()
    if not keys:
        return None

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
    }).encode()

    for key in keys:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": "https://github.com/basitdev/ashi",
                    "X-Title": "ASHI Planner",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue  # try next key
            return None
        except Exception:
            return None
    return None


# ── Step parsing ───────────────────────────────────────────────────────────────

def _parse_steps(raw: str, max_steps: int) -> list[str]:
    """
    Extract step strings from a numbered list. Caps at max_steps.
    Strips chain-of-thought reasoning that some models leak into output.
    """
    # strip <think>...</think> blocks (reasoning models)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    steps = []
    for line in lines:
        # only accept lines that start with a number (actual list items)
        if not re.match(r"^\d+[.):\-\s]", line):
            continue
        # strip "1." / "1)" / "1-" / "Step 1:" prefixes
        clean = re.sub(r"^(step\s*)?\d+[.):\-\s]+", "", line, flags=re.IGNORECASE).strip()
        # skip very long lines (likely reasoning paragraphs, not steps)
        if clean and 5 < len(clean) < 200:
            steps.append(clean)
    return steps[:max_steps]


def _normalise(step: str) -> str:
    """Lowercase + strip punctuation for fuzzy dedup."""
    return re.sub(r"[^a-z0-9\s]", "", step.lower()).strip()


def _merge_plans(plans: list[list[str]], max_steps: int) -> list[str]:
    """
    Merge N step lists by consensus voting.
    Steps present in 2+ plans appear first (consensus), then unique steps.
    Deduplicates by normalised text similarity.
    """
    if not plans:
        return []

    # count normalised step appearances across all plans
    from collections import Counter
    norm_to_original: dict[str, str] = {}
    counts: Counter = Counter()

    for plan in plans:
        seen_in_this_plan: set[str] = set()
        for step in plan:
            norm = _normalise(step)
            if norm and norm not in seen_in_this_plan:
                counts[norm] += 1
                seen_in_this_plan.add(norm)
                if norm not in norm_to_original:
                    norm_to_original[norm] = step  # keep first occurrence

    # sort: consensus steps first (count >= 2), then by plan order
    # preserve original ordering within each tier
    consensus = []
    unique = []
    seen_norms: set[str] = set()

    # walk plans in order to preserve sequencing
    for plan in plans:
        for step in plan:
            norm = _normalise(step)
            if norm in seen_norms:
                continue
            seen_norms.add(norm)
            canonical = norm_to_original.get(norm, step)
            if counts[norm] >= 2:
                consensus.append(canonical)
            else:
                unique.append(canonical)

    merged = consensus + unique
    return merged[:max_steps]


# ── HostAgent ──────────────────────────────────────────────────────────────────

def _call_ollama(system: str, user: str, model: str) -> tuple[str, int]:
    """Thin wrapper so tests can patch it."""
    text, tokens, _ = _call_with_fallback(system, user, model)
    return text, tokens


class HostAgent:
    def __init__(
        self,
        models: Optional[list[str]] = None,
        local_fallback: str = LOCAL_FALLBACK_MODEL,
    ):
        self.brain_models = models or BRAIN_MODELS
        self.local_fallback = local_fallback

    def _plan_multi_brain(self, system: str, user: str, max_steps: int) -> list[str]:
        """
        Call all brain models in parallel via OpenRouter.
        Returns merged step list, or empty list if all fail.
        """
        if not _get_or_keys():
            return []

        plans: list[list[str]] = []

        with ThreadPoolExecutor(max_workers=len(self.brain_models)) as executor:
            futures = {
                executor.submit(_call_openrouter_model, model, system, user): model
                for model in self.brain_models
            }
            for future in as_completed(futures):
                raw = future.result()
                if raw:
                    steps = _parse_steps(raw, max_steps)
                    if steps:
                        plans.append(steps)

        return _merge_plans(plans, max_steps) if plans else []

    def _plan_local(self, system: str, user: str, max_steps: int) -> list[str]:
        """Local fallback via Ollama."""
        raw, _ = _call_ollama(system, user, self.local_fallback)
        return _parse_steps(raw, max_steps)

    def plan(self, bb: Blackboard) -> list[str]:
        """
        Decompose bb.goal into a step list using multi-brain planning.
        Tries parallel OpenRouter calls first; falls back to local qwen3:4b.
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

        # try multi-brain first
        steps = self._plan_multi_brain(system, user, budget)[:budget]

        # fall back to local if cloud unavailable or all failed
        if not steps:
            print("[host_agent] Multi-brain unavailable, using local fallback", flush=True)
            steps = self._plan_local(system, user, budget)

        if not steps:
            steps = [f"Complete the goal: {bb.goal}"]

        bb.set_plan(steps)
        return steps
