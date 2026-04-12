"""
audit.py — ASHI audit logger.
Every IDE action, skill run, tool dispatch, and session event gets
written to ~/Desktop/SecondBrain/AI/agent-logs/audit-YYYY-MM-DD.jsonl
Each line is a JSON object: {ts, event, data, session_id}
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, date
from pathlib import Path
from typing import Any
from uuid import uuid4

# ── Module-level session ID (persists for process lifetime) ────────────────────

SESSION_ID: str = str(uuid4())

# ── Constants ──────────────────────────────────────────────────────────────────

_LOG_DIR = Path.home() / "Desktop" / "SecondBrain" / "AI" / "agent-logs"


# ── Path helper ────────────────────────────────────────────────────────────────


def _audit_path(date_str: str | None = None) -> Path:
    d = date_str or date.today().isoformat()
    return _LOG_DIR / f"audit-{d}.jsonl"


# ── Core writer ────────────────────────────────────────────────────────────────


def log_event(event: str, data: dict[str, Any]) -> None:
    """
    Append one JSON line to today's audit log.

    event: one of skill_run | tool_dispatch | ide_action | hook_fired |
                     session_start | session_end | error
    data:  arbitrary key/value pairs specific to the event type
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(tz=__import__("datetime").timezone.utc).isoformat(),
        "event": event,
        "data": data,
        "session_id": SESSION_ID,
    }
    with _audit_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── Typed helpers ──────────────────────────────────────────────────────────────


def log_skill_run(
    skill_name: str,
    system: str,
    model: str,
    tokens: int,
    success: bool,
) -> None:
    """Log a skill execution."""
    log_event(
        "skill_run",
        {
            "skill": skill_name,
            "system": system,
            "model": model,
            "tokens": tokens,
            "success": success,
        },
    )


def log_tool_dispatch(
    tool_name: str,
    args_keys: list[str],
    success: bool,
    duration_ms: float,
) -> None:
    """Log a tool dispatch call."""
    log_event(
        "tool_dispatch",
        {
            "tool": tool_name,
            "args_keys": args_keys,
            "success": success,
            "duration_ms": duration_ms,
        },
    )


def log_ide_action(action: str, ide: str, path: str, model: str) -> None:
    """Log an IDE control action."""
    log_event(
        "ide_action",
        {
            "action": action,
            "ide": ide,
            "path": path,
            "model": model,
        },
    )


# ── Backward-compatible alias (tool_dispatch.py imports log_tool) ──────────────


def log_tool(
    name: str,
    args_summary: str,
    result_summary: str,
    duration_ms: float | None = None,
    status: str = "ok",
) -> None:
    """
    Backward-compatible shim — used by tool_dispatch.py.
    Maps to log_event("tool_dispatch", ...).
    """
    log_event(
        "tool_dispatch",
        {
            "tool": name,
            "args_summary": args_summary,
            "result_summary": result_summary,
            "duration_ms": duration_ms,
            "success": status == "ok",
            "status": status,
        },
    )


# ── Summary ────────────────────────────────────────────────────────────────────


def _read_records(date_str: str | None = None) -> list[dict]:
    path = _audit_path(date_str)
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def get_today_summary(date_str: str | None = None) -> dict:
    """
    Read today's audit log, return aggregated stats.

    Returns:
        {
            "date": "YYYY-MM-DD",
            "total_events": int,
            "skills_run": int,
            "tools_dispatched": int,
            "ide_actions": int,
            "errors": int,
            "top_skills": list[str],   # top 5 by count
            "top_tools": list[str],    # top 5 by count
        }
    """
    d = date_str or date.today().isoformat()
    records = _read_records(d)

    skill_counter: Counter[str] = Counter()
    tool_counter: Counter[str] = Counter()
    skills_run = 0
    tools_dispatched = 0
    ide_actions = 0
    errors = 0

    for rec in records:
        event = rec.get("event", "")
        data = rec.get("data", {})
        if event == "skill_run":
            skills_run += 1
            skill_counter[data.get("skill", "unknown")] += 1
        elif event == "tool_dispatch":
            tools_dispatched += 1
            tool_counter[
                data.get("tool") or data.get("name", "unknown")
            ] += 1
        elif event == "ide_action":
            ide_actions += 1
        elif event == "error":
            errors += 1

    return {
        "date": d,
        "total_events": len(records),
        "skills_run": skills_run,
        "tools_dispatched": tools_dispatched,
        "ide_actions": ide_actions,
        "errors": errors,
        "top_skills": [name for name, _ in skill_counter.most_common(5)],
        "top_tools": [name for name, _ in tool_counter.most_common(5)],
    }


def get_audit_report(date_str: str | None = None) -> str:
    """
    Generate a markdown audit report for the given date (today if None).

    Returns a formatted markdown string with sections:
        Summary, Skills Used, Tools Dispatched, IDE Actions, Errors
    """
    d = date_str or date.today().isoformat()
    records = _read_records(d)
    summary = get_today_summary(d)

    lines: list[str] = [
        f"# ASHI Audit Report — {d}",
        "",
        "## Summary",
        f"- Total events: {summary['total_events']}",
        f"- Skills run: {summary['skills_run']}",
        f"- Tools dispatched: {summary['tools_dispatched']}",
        f"- IDE actions: {summary['ide_actions']}",
        f"- Errors: {summary['errors']}",
        "",
    ]

    # Skills Used
    lines.append("## Skills Used")
    skill_records = [r for r in records if r.get("event") == "skill_run"]
    if skill_records:
        for rec in skill_records:
            d_data = rec.get("data", {})
            ts = rec.get("ts", "")[:19]
            skill = d_data.get("skill", "?")
            model = d_data.get("model", "?")
            tokens = d_data.get("tokens", 0)
            ok = "ok" if d_data.get("success") else "fail"
            lines.append(
                f"- `{ts}` **{skill}** via {model} — {tokens} tokens [{ok}]"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    # Tools Dispatched
    lines.append("## Tools Dispatched")
    tool_records = [r for r in records if r.get("event") == "tool_dispatch"]
    if tool_records:
        for rec in tool_records:
            d_data = rec.get("data", {})
            ts = rec.get("ts", "")[:19]
            tool = d_data.get("tool") or d_data.get("name", "?")
            dur = d_data.get("duration_ms")
            dur_str = f"{dur:.1f}ms" if dur is not None else "?"
            ok = "ok" if d_data.get("success") else "fail"
            lines.append(f"- `{ts}` **{tool}** {dur_str} [{ok}]")
    else:
        lines.append("- (none)")
    lines.append("")

    # IDE Actions
    lines.append("## IDE Actions")
    ide_records = [r for r in records if r.get("event") == "ide_action"]
    if ide_records:
        for rec in ide_records:
            d_data = rec.get("data", {})
            ts = rec.get("ts", "")[:19]
            action = d_data.get("action", "?")
            ide = d_data.get("ide", "?")
            path = d_data.get("path", "")
            model = d_data.get("model", "")
            detail = (
                f" `{path}`"
                if path
                else (f" model={model}" if model else "")
            )
            lines.append(f"- `{ts}` **{action}** in {ide}{detail}")
    else:
        lines.append("- (none)")
    lines.append("")

    # Errors
    lines.append("## Errors")
    error_records = [r for r in records if r.get("event") == "error"]
    if error_records:
        for rec in error_records:
            d_data = rec.get("data", {})
            ts = rec.get("ts", "")[:19]
            msg = d_data.get("message", str(d_data))
            lines.append(f"- `{ts}` {msg}")
    else:
        lines.append("- (none)")

    return "\n".join(lines)
