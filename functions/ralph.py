"""
Ralph Loop — daily self-improvement cycle for ASHI.
Runs at 3am via cron. Scores skills, rewrites weak ones via Claude, promotes winners.

Usage:
    python -m functions.ralph           # run with default config
    python -m functions.ralph --dry-run # score only, no rewrites
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime

# ensure functions/ is importable
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from skill_scorer import score_skills, report_scores, SkillScore

SKILLS_PATH = os.path.expanduser("~/Desktop/SecondBrain/Projects/ashi/skills")
TASKS_PATH = os.path.expanduser("~/Desktop/SecondBrain/tasks")
RALPH_LOG_DIR = os.path.expanduser("~/Desktop/SecondBrain/AI/agent-logs")
WIKI_PATH = os.path.expanduser("~/Desktop/SecondBrain/wiki")
OLLAMA_URL = "http://localhost:11434/api/chat"
CLAUDE_MODEL = "claude-sonnet-4-6"

REWRITE_SYSTEM = """You are ASHI's skill author. You write skill files for a local AI OS.

A skill file has this structure:
```
---
name: <skill_name>
version: <N>
author: claude
model_hint: executor
---

## System
<system prompt for the local model>

## User Template
<template with {placeholders}>

## Output Format
<expected output structure>
```

You are rewriting an underperforming skill. Make it:
- More specific about what the model should output
- Clearer about which tools to call and when
- Stricter about output format (JSON preferred where applicable)
- Less likely to hallucinate or go off-task

Return ONLY the complete skill file contents, no explanation."""

REWRITE_USER = """Skill: {skill_name}
Current version: {current_version}
Performance: avg_score={avg_score}/10, fail_rate={fail_rate:.0%}, runs={runs}

Current skill file:
{current_content}

Recent failure patterns from TCU logs:
{failure_notes}

Rewrite this skill to improve performance. Increment the version number."""


def _load_skill_file(skill_name: str) -> str:
    path = os.path.join(SKILLS_PATH, f"{skill_name}.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


def _parse_version(content: str) -> int:
    import re
    m = re.search(r"^version:\s*(\d+)", content, re.MULTILINE)
    return int(m.group(1)) if m else 1


def _archive_skill(skill_name: str, content: str, version: int) -> str:
    archive_dir = os.path.join(SKILLS_PATH, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(archive_dir, f"{skill_name}-v{version}-{date_str}.md")
    with open(path, "w") as f:
        f.write(content)
    return path


def _write_skill(skill_name: str, content: str) -> None:
    path = os.path.join(SKILLS_PATH, f"{skill_name}.md")
    with open(path, "w") as f:
        f.write(content)


def _call_claude_for_rewrite(
    skill_name: str,
    current_content: str,
    score: SkillScore,
    failure_notes: str,
) -> str | None:
    """Call Claude (via Anthropic API or Ollama fallback) to rewrite a skill."""
    version = _parse_version(current_content)
    user_msg = REWRITE_USER.format(
        skill_name=skill_name,
        current_version=version,
        avg_score=score.avg_score,
        fail_rate=score.fail_rate,
        runs=score.runs,
        current_content=current_content,
        failure_notes=failure_notes or "No specific failure patterns available.",
    )

    # try Anthropic API first
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                system=REWRITE_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            return msg.content[0].text.strip()
        except Exception:
            pass

    # fallback: Ollama with planner model
    try:
        payload = {
            "model": "ashi-planner",
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
        return result["message"]["content"].strip()
    except Exception:
        return None


def _collect_failure_notes(skill_name: str, tasks_path: str) -> str:
    """Extract failure notes from recent TCUs that used this skill."""
    notes: list[str] = []
    for subdir in ("active", "done"):
        dirpath = os.path.join(tasks_path, subdir)
        if not os.path.isdir(dirpath):
            continue
        for fname in sorted(os.listdir(dirpath))[-20:]:
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(dirpath, fname)) as f:
                    tcu = json.load(f)
            except Exception:
                continue
            if tcu.get("skill") != skill_name:
                continue
            judge = tcu.get("judge", {})
            if judge.get("verdict") in ("fail", "retry"):
                notes.append(f"- {judge.get('notes', 'no notes')}")
    return "\n".join(notes[:5])


def _update_wiki_with_learnings(improvements: list[dict]) -> None:
    """Append Ralph Loop learnings to wiki/log.md."""
    log_path = os.path.join(WIKI_PATH, "log.md")
    if not os.path.exists(log_path):
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n## [{timestamp}] ralph-loop | Self-Improvement Cycle\n"]
    for item in improvements:
        lines.append(
            f"- `{item['skill']}`: v{item['old_version']} → v{item['new_version']} "
            f"(was {item['avg_score']:.1f}/10 avg)\n"
        )
    with open(log_path, "a") as f:
        f.writelines(lines)


def run_ralph(dry_run: bool = False, since_hours: int = 24) -> dict:
    """
    Execute one Ralph Loop cycle.

    Args:
        dry_run:     Score only — don't rewrite any skills
        since_hours: How many hours of TCU history to look at

    Returns:
        Summary dict: {"scored": N, "improved": N, "skipped": N, "errors": [...]}
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.path.join(RALPH_LOG_DIR, f"ralph-{date_str}.log")
    os.makedirs(RALPH_LOG_DIR, exist_ok=True)

    def log(msg: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"
        with open(log_file, "a") as f:
            f.write(line)
        print(line, end="")

    log(f"=== Ralph Loop started {'(DRY RUN) ' if dry_run else ''}===")

    scores = score_skills(TASKS_PATH, since_hours=since_hours)
    log(f"Scored {len(scores)} skills from last {since_hours}h of TCU history")

    if scores:
        log("\nSkill scores:\n" + report_scores(scores))

    weak = [s for s in scores.values() if s.needs_improvement]
    log(f"{len(weak)} skills need improvement: {[s.skill_name for s in weak]}")

    summary = {
        "scored": len(scores),
        "improved": 0,
        "skipped": 0,
        "errors": [],
        "improvements": [],
    }

    if dry_run:
        log("DRY RUN — skipping rewrites")
        return summary

    for score in weak:
        skill_name = score.skill_name
        current_content = _load_skill_file(skill_name)
        if not current_content:
            log(f"SKIP {skill_name}: skill file not found")
            summary["skipped"] += 1
            continue

        old_version = _parse_version(current_content)
        log(f"Rewriting {skill_name} (v{old_version}, avg={score.avg_score})")

        failure_notes = _collect_failure_notes(skill_name, TASKS_PATH)
        new_content = _call_claude_for_rewrite(skill_name, current_content, score, failure_notes)

        if not new_content or len(new_content) < 100:
            log(f"ERROR {skill_name}: rewrite returned empty/short content")
            summary["errors"].append(f"{skill_name}: empty rewrite")
            continue

        new_version = _parse_version(new_content)
        if new_version <= old_version:
            # force increment if model forgot to bump
            import re
            new_content = re.sub(
                r"^version:\s*\d+",
                f"version: {old_version + 1}",
                new_content,
                flags=re.MULTILINE,
            )
            new_version = old_version + 1

        # archive old, write new
        _archive_skill(skill_name, current_content, old_version)
        _write_skill(skill_name, new_content)

        log(f"Promoted {skill_name} v{old_version} → v{new_version}")
        summary["improved"] += 1
        summary["improvements"].append({
            "skill": skill_name,
            "old_version": old_version,
            "new_version": new_version,
            "avg_score": score.avg_score,
        })

    if summary["improvements"]:
        _update_wiki_with_learnings(summary["improvements"])

    log(f"=== Ralph Loop done: {summary['improved']} improved, {summary['skipped']} skipped, {len(summary['errors'])} errors ===")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASHI Ralph Loop — daily skill improvement")
    parser.add_argument("--dry-run", action="store_true", help="Score only, no rewrites")
    parser.add_argument("--since", type=int, default=24, help="Hours of history to scan (default: 24)")
    args = parser.parse_args()
    result = run_ralph(dry_run=args.dry_run, since_hours=args.since)
    print(json.dumps(result, indent=2))
