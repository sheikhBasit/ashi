"""
vizier_loop.py -- Proactive intelligence loop for ASHI.

Every VIZIER_INTERVAL_S (default 5 minutes), reads LiveContext, sends it to an
LLM with the question "What should ASHI do right now?", and either:
  - High confidence: executes automatically
  - Medium confidence: sends desktop notification for approval
  - Low confidence: logs suggestion, does nothing

All proactive actions are logged to ~/SecondBrain/AI/agent-logs/vizier.log.
"""

import asyncio
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ashi.vizier")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIZIER_INTERVAL_S = int(os.getenv("ASHI_VIZIER_INTERVAL_S", "300"))  # 5 min
VIZIER_MODEL = os.getenv("ASHI_VIZIER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
VIZIER_ENABLED = os.getenv("ASHI_VIZIER_ENABLED", "true").lower() in ("true", "1", "yes")

SECOND_BRAIN = Path(os.getenv("SECOND_BRAIN_PATH", os.path.expanduser("~/SecondBrain")))
VIZIER_LOG = SECOND_BRAIN / "AI" / "agent-logs" / "vizier.log"
LESSONS_DIR = SECOND_BRAIN / "AI" / "lessons"

# Confidence thresholds
AUTO_EXECUTE_THRESHOLD = 0.85
NOTIFY_THRESHOLD = 0.5

# Actions the Vizier is allowed to execute automatically
SAFE_AUTO_ACTIONS = {
    "send_notification",
    "write_reminder",
    "update_daily_note",
    "log_observation",
    "send_telegram",
}

# Actions that ALWAYS require confirmation
DANGEROUS_ACTIONS = {
    "run_shell",
    "git_commit",
    "git_push",
    "delete_file",
    "send_email",
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_VIZIER_SYSTEM = """\
You are ASHI's Vizier -- a proactive intelligence layer for Abdul Basit (Basit), \
a junior backend engineer. Your job is to look at what Basit is doing RIGHT NOW \
and suggest ONE helpful action.

Rules:
1. Only suggest things that are CLEARLY helpful based on the context.
2. Return EXACTLY one JSON object. No markdown, no explanation.
3. If nothing useful to do, return {"action": "none", "confidence": 0.0, "reason": "..."}
4. Confidence must be between 0.0 and 1.0:
   - 0.85+: ASHI will auto-execute (only for safe actions)
   - 0.5-0.84: ASHI will ask Basit for approval via notification
   - Below 0.5: ASHI logs it and does nothing

Available actions:
- send_notification: {"action": "send_notification", "title": str, "body": str, "confidence": float, "reason": str}
- write_reminder: {"action": "write_reminder", "text": str, "confidence": float, "reason": str}
- update_daily_note: {"action": "update_daily_note", "section": "todos"|"notes", "text": str, "confidence": float, "reason": str}
- log_observation: {"action": "log_observation", "text": str, "confidence": float, "reason": str}
- send_telegram: {"action": "send_telegram", "message": str, "confidence": float, "reason": str}
- run_shell: {"action": "run_shell", "command": str, "confidence": float, "reason": str}
- none: {"action": "none", "confidence": 0.0, "reason": str}

Context about Basit:
- Jr Backend Engineer at VillaEx Technologies, Lahore
- Works on NexaVoxa (voice AI platform) and ASHI (this AI OS)
- Stack: Python, TypeScript, Node.js, PostgreSQL
- Uses Ubuntu, terminal-first workflow
- Priorities: ASHI v0.2 ship, VillaEx features, personal brand
"""

_VIZIER_USER = """\
Current context:
{context}

Time since last check: {elapsed}

What should ASHI do right now to help Basit? Return ONE JSON action.
"""


# ---------------------------------------------------------------------------
# OpenRouter caller (reuse pattern from host_agent.py)
# ---------------------------------------------------------------------------

def _get_or_key() -> Optional[str]:
    """Get first available OpenRouter key."""
    for var in ("OPENROUTER_KEY_1", "OPENROUTER_KEY_2", "OPENROUTER_KEY_3", "OPENROUTER_API_KEY"):
        key = os.environ.get(var, "")
        if key:
            return key
    return None


def _call_vizier_llm(context_summary: str, elapsed_str: str) -> Optional[dict]:
    """Call the Vizier model and parse the JSON response."""
    key = _get_or_key()
    if not key:
        logger.warning("No OpenRouter API key available for Vizier")
        return None

    user_msg = _VIZIER_USER.format(context=context_summary, elapsed=elapsed_str)

    payload = json.dumps({
        "model": VIZIER_MODEL,
        "messages": [
            {"role": "system", "content": _VIZIER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
    }).encode()

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://github.com/basitdev/ashi",
                "X-Title": "ASHI Vizier",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        raw = result["choices"][0]["message"]["content"].strip()

        # Parse JSON from response
        # Strip markdown fences if present
        import re
        raw = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        logger.warning("Vizier LLM returned non-JSON: %s", e)
        return None
    except urllib.error.HTTPError as e:
        logger.warning("Vizier LLM HTTP error: %s", e.code)
        return None
    except Exception as e:
        logger.warning("Vizier LLM call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------

def _execute_send_notification(data: dict) -> str:
    """Send a desktop notification via notify-send."""
    title = data.get("title", "ASHI")
    body = data.get("body", "")
    try:
        subprocess.run(
            ["notify-send", "-a", "ASHI", "-i", "dialog-information", title, body],
            timeout=5,
        )
        return f"Notification sent: {title}"
    except Exception as e:
        return f"Notification failed: {e}"


def _execute_write_reminder(data: dict) -> str:
    """Write a reminder to today's daily note."""
    text = data.get("text", "")
    if not text:
        return "Empty reminder, skipped"

    today = datetime.now().strftime("%Y-%m-%d")
    note_path = SECOND_BRAIN / "Daily" / f"{today}.md"

    note_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        timestamp = datetime.now().strftime("%H:%M")
        entry = f"\n- [{timestamp}] ASHI reminder: {text}\n"

        if note_path.exists():
            with open(note_path, "a", encoding="utf-8") as f:
                f.write(entry)
        else:
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(f"# {today}\n\n## ASHI Notes\n{entry}")

        return f"Reminder written to {note_path.name}"
    except Exception as e:
        return f"Write reminder failed: {e}"


def _execute_update_daily_note(data: dict) -> str:
    """Append to a section of today's daily note."""
    section = data.get("section", "notes")
    text = data.get("text", "")
    if not text:
        return "Empty update, skipped"

    today = datetime.now().strftime("%Y-%m-%d")
    note_path = SECOND_BRAIN / "Daily" / f"{today}.md"

    try:
        timestamp = datetime.now().strftime("%H:%M")
        if section == "todos":
            entry = f"- [ ] {text} (ASHI {timestamp})\n"
        else:
            entry = f"- [{timestamp}] {text}\n"

        with open(note_path, "a", encoding="utf-8") as f:
            f.write(entry)

        return f"Daily note updated: {section}"
    except Exception as e:
        return f"Daily note update failed: {e}"


def _execute_log_observation(data: dict) -> str:
    """Log an observation -- no side effects, just recording."""
    text = data.get("text", "")
    # This is logged by the main vizier log, so just return
    return f"Observation logged: {text[:100]}"


_ACTION_EXECUTORS = {
    "send_notification": _execute_send_notification,
    "write_reminder": _execute_write_reminder,
    "update_daily_note": _execute_update_daily_note,
    "log_observation": _execute_log_observation,
}


# ---------------------------------------------------------------------------
# Vizier log
# ---------------------------------------------------------------------------

def _log_vizier_action(action: dict, result: str, auto_executed: bool) -> None:
    """Append to the Vizier log file."""
    VIZIER_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "action": action.get("action", "unknown"),
        "confidence": action.get("confidence", 0.0),
        "reason": action.get("reason", ""),
        "auto_executed": auto_executed,
        "result": result,
    }
    with open(VIZIER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Notification for approval
# ---------------------------------------------------------------------------

def _notify_for_approval(action: dict) -> None:
    """Send a notification asking Basit to approve an action."""
    action_type = action.get("action", "unknown")
    reason = action.get("reason", "")
    confidence = action.get("confidence", 0.0)

    title = f"ASHI Vizier ({confidence:.0%})"
    body = f"Suggested: {action_type}\n{reason}"

    try:
        subprocess.run(
            ["notify-send", "-a", "ASHI Vizier", "-u", "normal",
             "-i", "dialog-question", title, body],
            timeout=5,
        )
    except Exception as e:
        logger.warning("Approval notification failed: %s", e)


# ---------------------------------------------------------------------------
# Main Vizier loop
# ---------------------------------------------------------------------------

async def _vizier_tick(last_check_time: float) -> float:
    """One iteration of the Vizier loop. Returns current time."""
    from context_engine import get_context

    ctx = get_context()
    if not ctx.last_updated:
        logger.debug("Context not yet populated, skipping vizier tick")
        return time.time()

    elapsed = time.time() - last_check_time
    elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    context_summary = ctx.summary()

    # Call LLM
    loop = asyncio.get_event_loop()
    action = await loop.run_in_executor(
        None,
        _call_vizier_llm,
        context_summary,
        elapsed_str,
    )

    if not action or not isinstance(action, dict):
        logger.debug("Vizier: no valid action returned")
        return time.time()

    action_type = action.get("action", "none")
    confidence = float(action.get("confidence", 0.0))
    reason = action.get("reason", "")

    if action_type == "none" or confidence < NOTIFY_THRESHOLD:
        logger.debug("Vizier: %s (confidence=%.2f, reason=%s)", action_type, confidence, reason[:80])
        _log_vizier_action(action, "skipped (below threshold)", False)
        return time.time()

    # High confidence + safe action = auto-execute
    if confidence >= AUTO_EXECUTE_THRESHOLD and action_type in SAFE_AUTO_ACTIONS:
        executor = _ACTION_EXECUTORS.get(action_type)
        if executor:
            try:
                result = executor(action)
                logger.info("Vizier auto-executed: %s -> %s", action_type, result[:100])
                _log_vizier_action(action, result, True)
            except Exception as e:
                logger.error("Vizier auto-execute failed: %s", e)
                _log_vizier_action(action, f"error: {e}", True)
        else:
            logger.warning("Vizier: no executor for safe action %s", action_type)
            _log_vizier_action(action, "no executor", False)
        return time.time()

    # Dangerous action or medium confidence = notify for approval
    if action_type in DANGEROUS_ACTIONS:
        logger.info("Vizier: dangerous action %s needs approval (confidence=%.2f)", action_type, confidence)
        _notify_for_approval(action)
        _log_vizier_action(action, "awaiting approval (dangerous)", False)
    else:
        logger.info("Vizier: medium confidence action %s (%.2f)", action_type, confidence)
        _notify_for_approval(action)
        _log_vizier_action(action, "awaiting approval (medium confidence)", False)

    return time.time()


async def run_vizier_loop() -> None:
    """Main loop. Call this as an asyncio task from the daemon."""
    if not VIZIER_ENABLED:
        logger.info("Vizier loop disabled (ASHI_VIZIER_ENABLED=false)")
        return

    logger.info("Vizier loop starting (interval=%ds, model=%s)", VIZIER_INTERVAL_S, VIZIER_MODEL)

    # Wait for context engine to populate initial data
    await asyncio.sleep(60)

    last_check = time.time()

    while True:
        try:
            last_check = await _vizier_tick(last_check)
        except Exception as e:
            logger.error("Vizier loop error: %s", e, exc_info=True)

        await asyncio.sleep(VIZIER_INTERVAL_S)


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    async def _test():
        from context_engine import _update_context_once
        await _update_context_once()
        await _vizier_tick(time.time() - 300)

    asyncio.run(_test())
