"""
User intent extraction and append-only intent log management.
Uses keyword heuristics — no LLM call needed for basic routing.
"""
import re
from datetime import datetime
from typing import Optional

_FIX_KEYWORDS = ["fix", "bug", "error", "crash", "broken", "wrong", "issue", "debug"]
_BUILD_KEYWORDS = ["build", "create", "add", "implement", "make", "write", "generate"]
_RESEARCH_KEYWORDS = ["research", "find", "search", "look up", "investigate", "explore"]
_PLAN_KEYWORDS = ["plan", "design", "architect", "spec", "outline", "structure"]


def extract_intent(user_message: str) -> dict:
    msg = user_message.lower().strip()
    mode = "feature"
    if any(kw in msg for kw in _FIX_KEYWORDS):
        mode = "fix"
    elif any(kw in msg for kw in _RESEARCH_KEYWORDS):
        mode = "research"
    elif any(kw in msg for kw in _PLAN_KEYWORDS):
        mode = "plan"

    action = "build"
    all_keywords = _BUILD_KEYWORDS + _FIX_KEYWORDS + _RESEARCH_KEYWORDS + _PLAN_KEYWORDS
    for kw in all_keywords:
        if msg.startswith(kw):
            action = kw
            break

    return {
        "raw": user_message,
        "mode": mode,
        "action": action,
        "extracted_at": datetime.now().isoformat(),
    }


def append_intent_log(
    log_path: str,
    intent: str,
    outcome: str = "pending",
    satisfaction: str = "pending",
    task_id: Optional[str] = None,
):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    task_ref = f" | task: {task_id}" if task_id else ""
    line = (
        f"## [{timestamp}] intent: {intent} | outcome: {outcome}"
        f" | satisfaction: {satisfaction}{task_ref}\n"
    )
    with open(log_path, "a") as f:
        f.write(line)


def parse_intent_log(log_path: str) -> list[dict]:
    entries = []
    pattern = re.compile(
        r"## \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] intent: (.+?) \| outcome: (\w+) \| satisfaction: (\w+)"
    )
    with open(log_path) as f:
        for line in f:
            m = pattern.match(line.strip())
            if m:
                entries.append(
                    {
                        "timestamp": m.group(1),
                        "intent": m.group(2),
                        "outcome": m.group(3),
                        "satisfaction": m.group(4),
                    }
                )
    return entries
