import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from skill_scorer import score_skills, report_scores, SkillScore
from ralph import run_ralph, _parse_version, _archive_skill, _collect_failure_notes


def _make_tcu(tasks_dir: str, skill: str, verdict: str, score: int) -> None:
    import uuid
    from datetime import datetime
    done_dir = os.path.join(tasks_dir, "done")
    os.makedirs(done_dir, exist_ok=True)
    tcu_id = f"test_{uuid.uuid4().hex[:6]}"
    data = {
        "id": tcu_id,
        "intent": f"test task for {skill}",
        "skill": skill,
        "status": "done",
        "completed_at": datetime.now().isoformat(),
        "steps": {"1": {"name": skill, "status": "done", "output": "result"}},
        "judge": {"score": score, "verdict": verdict, "notes": f"test verdict {verdict}"},
    }
    with open(os.path.join(done_dir, f"{tcu_id}.json"), "w") as f:
        json.dump(data, f)


def test_score_skills_basic():
    with tempfile.TemporaryDirectory() as tmp:
        _make_tcu(tmp, "research", "pass", 9)
        _make_tcu(tmp, "research", "pass", 8)
        _make_tcu(tmp, "code", "fail", 2)
        _make_tcu(tmp, "code", "fail", 3)

        scores = score_skills(tasks_path=tmp, since_hours=24)
        assert "research" in scores
        assert "code" in scores
        assert scores["research"].avg_score >= 8.0
        assert scores["code"].needs_improvement is True
        assert scores["research"].needs_improvement is False


def test_report_scores_format():
    scores = {
        "research": SkillScore("research", runs=5, total_score=40.0),
        "code": SkillScore("code", runs=3, total_score=12.0, failures=1),
    }
    report = report_scores(scores)
    assert "research" in report
    assert "code" in report
    assert "|" in report  # markdown table


def test_parse_version():
    content = "---\nname: research\nversion: 3\nauthor: claude\n---\n## System\ntest"
    assert _parse_version(content) == 3

    assert _parse_version("no version here") == 1


def test_ralph_dry_run():
    with tempfile.TemporaryDirectory() as tmp:
        tasks_dir = os.path.join(tmp, "tasks")
        log_dir = os.path.join(tmp, "logs")
        skills_dir = os.path.join(tmp, "skills")
        os.makedirs(tasks_dir)
        os.makedirs(log_dir)
        os.makedirs(skills_dir)

        _make_tcu(tasks_dir, "code", "fail", 2)
        _make_tcu(tasks_dir, "code", "fail", 3)

        with patch("ralph.TASKS_PATH", tasks_dir), \
             patch("ralph.RALPH_LOG_DIR", log_dir), \
             patch("ralph.SKILLS_PATH", skills_dir), \
             patch("ralph.WIKI_PATH", tmp):
            result = run_ralph(dry_run=True, since_hours=24)

        assert result["improved"] == 0  # dry run — no changes
        assert result["scored"] >= 0
        # log file created
        import glob
        logs = glob.glob(os.path.join(log_dir, "ralph-*.log"))
        assert len(logs) == 1


def test_ralph_improves_weak_skill():
    with tempfile.TemporaryDirectory() as tmp:
        tasks_dir = os.path.join(tmp, "tasks")
        log_dir = os.path.join(tmp, "logs")
        skills_dir = os.path.join(tmp, "skills")
        wiki_dir = os.path.join(tmp, "wiki")
        os.makedirs(tasks_dir)
        os.makedirs(log_dir)
        os.makedirs(skills_dir)
        os.makedirs(wiki_dir)

        # create a weak skill
        skill_content = "---\nname: code\nversion: 1\nauthor: claude\nmodel_hint: executor\n---\n\n## System\nWrite code.\n\n## User Template\n{spec}\n\n## Output Format\nCode block.\n"
        with open(os.path.join(skills_dir, "code.md"), "w") as f:
            f.write(skill_content)

        # 3 failed runs
        _make_tcu(tasks_dir, "code", "fail", 2)
        _make_tcu(tasks_dir, "code", "fail", 3)
        _make_tcu(tasks_dir, "code", "retry", 5)

        new_skill = "---\nname: code\nversion: 2\nauthor: claude\nmodel_hint: executor\n---\n\n## System\nImproved code writer.\n\n## User Template\n{spec}\n\n## Output Format\nCode block.\n"

        with patch("ralph.TASKS_PATH", tasks_dir), \
             patch("ralph.RALPH_LOG_DIR", log_dir), \
             patch("ralph.SKILLS_PATH", skills_dir), \
             patch("ralph.WIKI_PATH", wiki_dir), \
             patch("ralph._call_claude_for_rewrite", return_value=new_skill):
            result = run_ralph(dry_run=False, since_hours=24)

        assert result["improved"] == 1
        # new skill written
        with open(os.path.join(skills_dir, "code.md")) as f:
            updated = f.read()
        assert "version: 2" in updated
        # old skill archived
        import glob
        archived = glob.glob(os.path.join(skills_dir, "archive", "code-v1-*.md"))
        assert len(archived) == 1
