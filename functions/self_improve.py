"""
self_improve.py -- Self-improvement loop for ASHI.

After each agent run:
  1. Evaluates: did it succeed? what failed? what would it do differently?
  2. Writes lessons to ~/SecondBrain/AI/lessons/
  3. Periodically reviews lessons and generates improvement summaries

Lessons are markdown files. ASHI reads them on startup to improve future runs.
Prompt modification is MANUAL ONLY -- ASHI never auto-edits its own system prompts.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ashi.self_improve")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SECOND_BRAIN = Path(os.getenv("SECOND_BRAIN_PATH", os.path.expanduser("~/SecondBrain")))
LESSONS_DIR = SECOND_BRAIN / "AI" / "lessons"
LESSONS_DIR.mkdir(parents=True, exist_ok=True)

REVIEW_INTERVAL_RUNS = int(os.getenv("ASHI_REVIEW_INTERVAL_RUNS", "10"))

# Track runs since last review
_runs_since_review = 0


# ---------------------------------------------------------------------------
# Lesson writing
# ---------------------------------------------------------------------------

def evaluate_run(
    goal: str,
    status: str,
    steps_completed: int,
    steps_total: int,
    outputs: list[dict],
    error: Optional[str] = None,
) -> dict:
    """
    Evaluate an agent run and extract lessons.

    Returns:
        {
            "success": bool,
            "score": float (0-1),
            "lessons": [str],
            "failures": [str],
            "improvements": [str],
        }
    """
    success = status in ("done", "completed", "success")
    successful_steps = sum(1 for o in outputs if o.get("success"))
    total = max(len(outputs), 1)
    score = successful_steps / total

    lessons = []
    failures = []
    improvements = []

    # Analyze each step
    for i, output in enumerate(outputs):
        step_text = output.get("step", f"Step {i+1}")
        tool_used = output.get("tool_used", "unknown")

        if not output.get("success"):
            error_msg = output.get("error", "unknown")
            failures.append(f"Step '{step_text}' failed: {error_msg}")

            # Extract improvement suggestions from error patterns
            if "JSON parse error" in error_msg:
                improvements.append(
                    f"Tool '{tool_used}': model output format issue. "
                    "Consider adding format enforcement or retry logic."
                )
            elif "timeout" in error_msg.lower():
                improvements.append(
                    f"Tool '{tool_used}': timed out. Consider increasing timeout or "
                    "breaking into smaller operations."
                )
            elif "argument error" in error_msg.lower():
                improvements.append(
                    f"Tool '{tool_used}': wrong arguments. "
                    "System prompt may need clearer arg documentation."
                )
            elif "unknown tool" in error_msg.lower():
                improvements.append(
                    "Model tried to use nonexistent tool. "
                    "Available tool list in system prompt may be outdated."
                )

    # Overall lessons
    if success and score == 1.0:
        lessons.append(f"Perfect run for goal type: '{goal[:60]}'. No changes needed.")
    elif success and score < 1.0:
        lessons.append(
            f"Completed with {len(failures)} failed steps out of {total}. "
            f"Partial success rate: {score:.0%}."
        )
    elif not success:
        if error and "consecutive failures" in error:
            lessons.append(
                "Run stopped due to consecutive failures. "
                "Planning may have produced steps the executor cannot handle."
            )
        elif error and "Planning failed" in error:
            lessons.append(
                "Planning phase failed entirely. "
                "Check if planner model is available and responsive."
            )
        else:
            lessons.append(f"Run failed: {error or 'unknown reason'}")

    return {
        "success": success,
        "score": score,
        "lessons": lessons,
        "failures": failures,
        "improvements": improvements,
    }


def write_lesson(
    goal: str,
    evaluation: dict,
) -> Optional[str]:
    """
    Write a lesson file to ~/SecondBrain/AI/lessons/.
    Only writes if there is something to learn (not perfect runs).

    Returns path to lesson file, or None if nothing to write.
    """
    if evaluation.get("success") and evaluation.get("score", 0) == 1.0:
        # Perfect run -- nothing to learn
        return None

    if not evaluation.get("lessons") and not evaluation.get("improvements"):
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}_lesson.md"
    filepath = LESSONS_DIR / filename

    lines = [
        f"# Lesson — {timestamp}",
        "",
        f"**Goal:** {goal}",
        f"**Status:** {'Success' if evaluation['success'] else 'Failed'}",
        f"**Score:** {evaluation['score']:.0%}",
        "",
    ]

    if evaluation.get("failures"):
        lines.append("## Failures")
        for f in evaluation["failures"]:
            lines.append(f"- {f}")
        lines.append("")

    if evaluation.get("lessons"):
        lines.append("## Lessons")
        for l in evaluation["lessons"]:
            lines.append(f"- {l}")
        lines.append("")

    if evaluation.get("improvements"):
        lines.append("## Improvements")
        for imp in evaluation["improvements"]:
            lines.append(f"- {imp}")
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Lesson written: %s", filepath)
    return str(filepath)


def on_run_complete(
    goal: str,
    status: str,
    steps_completed: int,
    steps_total: int,
    outputs: list[dict],
    error: Optional[str] = None,
) -> dict:
    """
    Called after every agent run. Evaluates and writes lessons.
    Returns the evaluation dict.
    """
    global _runs_since_review

    evaluation = evaluate_run(goal, status, steps_completed, steps_total, outputs, error)
    lesson_path = write_lesson(goal, evaluation)

    if lesson_path:
        evaluation["lesson_file"] = lesson_path

    _runs_since_review += 1

    # Periodic review
    if _runs_since_review >= REVIEW_INTERVAL_RUNS:
        try:
            review_path = generate_review()
            if review_path:
                evaluation["review_file"] = review_path
            _runs_since_review = 0
        except Exception as e:
            logger.error("Review generation failed: %s", e)

    return evaluation


# ---------------------------------------------------------------------------
# Lesson reading (for prompt context)
# ---------------------------------------------------------------------------

def get_recent_lessons(n: int = 5) -> list[dict]:
    """
    Read the N most recent lesson files.
    Returns list of {"file": str, "goal": str, "lessons": [str], "improvements": [str]}.
    """
    if not LESSONS_DIR.is_dir():
        return []

    files = sorted(LESSONS_DIR.glob("*_lesson.md"), reverse=True)[:n]
    results = []

    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
            goal = ""
            lessons = []
            improvements = []

            in_lessons = False
            in_improvements = False

            for line in content.splitlines():
                if line.startswith("**Goal:**"):
                    goal = line.replace("**Goal:**", "").strip()
                elif line.startswith("## Lessons"):
                    in_lessons = True
                    in_improvements = False
                elif line.startswith("## Improvements"):
                    in_lessons = False
                    in_improvements = True
                elif line.startswith("## "):
                    in_lessons = False
                    in_improvements = False
                elif line.startswith("- ") and in_lessons:
                    lessons.append(line[2:])
                elif line.startswith("- ") and in_improvements:
                    improvements.append(line[2:])

            results.append({
                "file": f.name,
                "goal": goal,
                "lessons": lessons,
                "improvements": improvements,
            })
        except Exception as e:
            logger.debug("Failed to read lesson %s: %s", f, e)

    return results


def get_lessons_summary(max_tokens: int = 500) -> str:
    """
    Get a compact text summary of recent lessons for prompt injection.
    """
    lessons = get_recent_lessons(5)
    if not lessons:
        return ""

    lines = ["Recent ASHI lessons (self-improvement):"]
    for l in lessons:
        if l.get("improvements"):
            for imp in l["improvements"][:2]:
                lines.append(f"- {imp}")
        elif l.get("lessons"):
            for les in l["lessons"][:1]:
                lines.append(f"- {les}")

    text = "\n".join(lines)
    if len(text) > max_tokens * 4:  # rough char-to-token ratio
        text = text[: max_tokens * 4]
    return text


# ---------------------------------------------------------------------------
# Periodic review
# ---------------------------------------------------------------------------

def generate_review() -> Optional[str]:
    """
    Read all unreviewed lessons and generate a summary review.
    Returns path to review file.
    """
    lessons = get_recent_lessons(20)
    if not lessons:
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    review_file = LESSONS_DIR / f"{timestamp}_review.md"

    # Aggregate
    all_improvements = []
    all_failures = []
    success_count = 0
    total_count = len(lessons)

    for l in lessons:
        all_improvements.extend(l.get("improvements", []))
        if not l.get("lessons") or "Failed" not in str(l.get("lessons", [])):
            success_count += 1

    # Deduplicate improvements by similarity
    unique_improvements = list(dict.fromkeys(all_improvements))

    lines = [
        f"# ASHI Self-Review — {timestamp}",
        "",
        f"**Runs reviewed:** {total_count}",
        f"**Success rate:** {success_count}/{total_count}",
        "",
        "## Top Improvements Needed",
        "",
    ]

    for imp in unique_improvements[:10]:
        lines.append(f"- {imp}")

    lines.append("")
    lines.append("## Action Items (for Basit to review)")
    lines.append("")
    lines.append("- [ ] Review improvements above")
    lines.append("- [ ] Update system prompts if needed")
    lines.append("- [ ] Check tool documentation in task_agent.py")
    lines.append("")

    review_file.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Review generated: %s", review_file)
    return str(review_file)


# ---------------------------------------------------------------------------
# Tool functions for tool_dispatch.py
# ---------------------------------------------------------------------------

def tool_get_lessons(n: int = 5) -> dict:
    """Get recent self-improvement lessons."""
    return {"lessons": get_recent_lessons(n)}


def tool_get_review() -> dict:
    """Generate and return a self-improvement review."""
    path = generate_review()
    if path:
        return {"review_file": path, "status": "generated"}
    return {"status": "no lessons to review"}
