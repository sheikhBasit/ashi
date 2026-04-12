import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from run_skill import run_skill, _load_skill, _render_template, SkillNotFoundError


SAMPLE_SKILL = """\
---
name: test-skill
version: 1
author: test
model_hint: executor
---

## System
You are a test assistant.

## User Template
Hello {name}, please do {task}.

## Output Format
Plain text response.
"""


def _write_skill(skills_dir: str, name: str, content: str) -> None:
    with open(os.path.join(skills_dir, f"{name}.md"), "w") as f:
        f.write(content)


def test_load_skill():
    with tempfile.TemporaryDirectory() as tmp:
        _write_skill(tmp, "test-skill", SAMPLE_SKILL)
        skill = _load_skill("test-skill", tmp)
        assert skill["name"] == "test-skill"
        assert skill["model_hint"] == "executor"
        assert "You are a test assistant" in skill["system"]
        assert "Hello {name}" in skill["user_template"]


def test_skill_not_found():
    import pytest
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SkillNotFoundError):
            _load_skill("nonexistent", tmp)


def test_render_template():
    template = "Hello {name}, please do {task}."
    result = _render_template(template, {"name": "ASHI", "task": "research"})
    assert result == "Hello ASHI, please do research."


def test_render_template_missing_key():
    template = "Hello {name}, see {missing_key}."
    result = _render_template(template, {"name": "ASHI"})
    assert "{missing_key}" in result  # missing keys preserved


def test_run_skill_mocked():
    with tempfile.TemporaryDirectory() as tmp:
        _write_skill(tmp, "test-skill", SAMPLE_SKILL)
        mock_output = ("Test output", 42)

        with patch("run_skill._call_ollama", return_value=mock_output):
            with patch("run_skill.LOG_PATH", tmp):
                result = run_skill(
                    "test-skill",
                    {"name": "World", "task": "testing"},
                    model="executor",
                    skills_path=tmp,
                )

        assert result["output"] == "Test output"
        assert result["tokens_used"] == 42
        assert result["skill"] == "test-skill"
