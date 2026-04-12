"""
skill_scorer — reads TCU history and scores each skill by performance.
Input: tasks/active/ + tasks/done/ JSON files
Output: dict of skill_name → SkillScore
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

TASKS_PATH = os.path.expanduser("~/Desktop/SecondBrain/tasks")


@dataclass
class SkillScore:
    skill_name: str
    runs: int = 0
    total_score: float = 0.0
    failures: int = 0
    retries: int = 0
    last_run: str = ""

    @property
    def avg_score(self) -> float:
        return round(self.total_score / self.runs, 2) if self.runs > 0 else 0.0

    @property
    def fail_rate(self) -> float:
        return round(self.failures / self.runs, 2) if self.runs > 0 else 0.0

    @property
    def needs_improvement(self) -> bool:
        return self.runs >= 2 and (self.avg_score < 6.0 or self.fail_rate > 0.30)

    def to_dict(self) -> dict:
        return {
            "skill": self.skill_name,
            "runs": self.runs,
            "avg_score": self.avg_score,
            "fail_rate": self.fail_rate,
            "failures": self.failures,
            "retries": self.retries,
            "last_run": self.last_run,
            "needs_improvement": self.needs_improvement,
        }


def _load_tcus(tasks_path: str, since_hours: int = 24) -> list[dict]:
    """Load TCU JSON files from active/ and done/ modified within since_hours."""
    tcus: list[dict] = []
    cutoff = datetime.now() - timedelta(hours=since_hours)

    for subdir in ("active", "done"):
        dirpath = os.path.join(tasks_path, subdir)
        if not os.path.isdir(dirpath):
            continue
        for fname in os.listdir(dirpath):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(dirpath, fname)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                continue
            try:
                with open(fpath) as f:
                    tcus.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass

    return tcus


def _extract_skill_from_tcu(tcu: dict) -> str | None:
    """
    Try to find which skill was used in this TCU.
    Checks steps for run_skill calls or a top-level 'skill' key.
    """
    if "skill" in tcu:
        return tcu["skill"]

    steps = tcu.get("steps", {})
    if isinstance(steps, dict):
        step_list = list(steps.values())
    else:
        step_list = steps

    for step in step_list:
        if isinstance(step, dict):
            name = step.get("name", "")
            if name and name not in ("research", "plan", "code", "review",
                                     "ingest", "daily-report", "wiki-update"):
                continue
            if name:
                return name

    return None


def score_skills(tasks_path: str = TASKS_PATH, since_hours: int = 24) -> dict[str, SkillScore]:
    """
    Read TCU history and score each skill.

    Returns:
        Dict of skill_name → SkillScore
    """
    tcus = _load_tcus(tasks_path, since_hours)
    scores: dict[str, SkillScore] = {}

    for tcu in tcus:
        skill_name = _extract_skill_from_tcu(tcu)
        if not skill_name:
            continue

        judge = tcu.get("judge", {})
        if not judge:
            continue

        verdict = judge.get("verdict", "unknown")
        score_val = float(judge.get("score", 0))
        completed_at = tcu.get("completed_at", "")

        if skill_name not in scores:
            scores[skill_name] = SkillScore(skill_name=skill_name)

        s = scores[skill_name]
        s.runs += 1
        s.total_score += score_val
        if verdict == "fail":
            s.failures += 1
        elif verdict == "retry":
            s.retries += 1
        if completed_at > s.last_run:
            s.last_run = completed_at

    return scores


def report_scores(scores: dict[str, SkillScore]) -> str:
    """Format scores as a markdown table for the ralph log."""
    if not scores:
        return "No skill runs found in the time window.\n"

    lines = [
        "| Skill | Runs | Avg Score | Fail Rate | Needs Work |",
        "|-------|------|-----------|-----------|------------|",
    ]
    for s in sorted(scores.values(), key=lambda x: x.avg_score):
        flag = "YES" if s.needs_improvement else "no"
        lines.append(
            f"| {s.skill_name} | {s.runs} | {s.avg_score} | {s.fail_rate:.0%} | {flag} |"
        )
    return "\n".join(lines) + "\n"
