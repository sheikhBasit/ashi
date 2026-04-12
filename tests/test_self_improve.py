"""Tests for self_improve.py"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from self_improve import (
    evaluate_run,
    write_lesson,
    get_recent_lessons,
    get_lessons_summary,
    on_run_complete,
)


class TestEvaluateRun:
    def test_perfect_run(self):
        result = evaluate_run(
            goal="Search wiki",
            status="done",
            steps_completed=3,
            steps_total=3,
            outputs=[
                {"success": True, "step": "step1", "tool_used": "search_wiki"},
                {"success": True, "step": "step2", "tool_used": "run_shell"},
                {"success": True, "step": "step3", "tool_used": "append_wiki_log"},
            ],
        )
        assert result["success"] is True
        assert result["score"] == 1.0
        assert len(result["failures"]) == 0

    def test_partial_failure(self):
        result = evaluate_run(
            goal="Complex task",
            status="done",
            steps_completed=3,
            steps_total=3,
            outputs=[
                {"success": True, "step": "step1", "tool_used": "search_wiki"},
                {"success": False, "step": "step2", "tool_used": "run_shell", "error": "timeout"},
                {"success": True, "step": "step3", "tool_used": "append_wiki_log"},
            ],
        )
        assert result["success"] is True
        assert result["score"] == pytest.approx(2 / 3)
        assert len(result["failures"]) == 1
        assert "timeout" in result["improvements"][0].lower()

    def test_complete_failure(self):
        result = evaluate_run(
            goal="Broken task",
            status="failed",
            steps_completed=2,
            steps_total=3,
            outputs=[
                {"success": False, "step": "step1", "tool_used": "run_shell", "error": "JSON parse error: bad"},
                {"success": False, "step": "step2", "tool_used": "unknown_tool", "error": "unknown tool 'bad'"},
            ],
            error="Stopped after 2 consecutive failures",
        )
        assert result["success"] is False
        assert result["score"] == 0.0
        assert len(result["failures"]) == 2
        assert any("format" in imp.lower() for imp in result["improvements"])

    def test_argument_error_improvement(self):
        result = evaluate_run(
            goal="Test",
            status="done",
            steps_completed=1,
            steps_total=1,
            outputs=[
                {"success": False, "step": "step1", "tool_used": "search_wiki", "error": "argument error: missing required"},
            ],
        )
        assert any("argument" in imp.lower() for imp in result["improvements"])


class TestWriteLesson:
    def test_skip_perfect_run(self):
        evaluation = {"success": True, "score": 1.0, "lessons": ["Perfect"], "failures": [], "improvements": []}
        result = write_lesson("Test goal", evaluation)
        assert result is None

    def test_writes_lesson_for_failure(self, tmp_path):
        import self_improve
        original = self_improve.LESSONS_DIR
        self_improve.LESSONS_DIR = tmp_path

        try:
            evaluation = {
                "success": False,
                "score": 0.5,
                "lessons": ["Something broke"],
                "failures": ["Step X failed"],
                "improvements": ["Try different approach"],
            }
            result = write_lesson("Fix the bug", evaluation)
            assert result is not None
            assert Path(result).exists()

            content = Path(result).read_text()
            assert "Fix the bug" in content
            assert "Something broke" in content
            assert "Try different approach" in content
        finally:
            self_improve.LESSONS_DIR = original


class TestGetLessons:
    def test_get_recent_lessons_empty(self, tmp_path):
        import self_improve
        original = self_improve.LESSONS_DIR
        self_improve.LESSONS_DIR = tmp_path

        try:
            result = get_recent_lessons()
            assert result == []
        finally:
            self_improve.LESSONS_DIR = original

    def test_get_recent_lessons_with_files(self, tmp_path):
        import self_improve
        original = self_improve.LESSONS_DIR
        self_improve.LESSONS_DIR = tmp_path

        try:
            # Write a lesson file
            lesson = tmp_path / "2026-04-11_120000_lesson.md"
            lesson.write_text(
                "# Lesson\n\n"
                "**Goal:** Test goal\n\n"
                "## Lessons\n"
                "- Something went wrong\n\n"
                "## Improvements\n"
                "- Try X instead\n"
            )

            result = get_recent_lessons(5)
            assert len(result) == 1
            assert result[0]["goal"] == "Test goal"
            assert "Something went wrong" in result[0]["lessons"]
            assert "Try X instead" in result[0]["improvements"]
        finally:
            self_improve.LESSONS_DIR = original

    def test_get_lessons_summary(self, tmp_path):
        import self_improve
        original = self_improve.LESSONS_DIR
        self_improve.LESSONS_DIR = tmp_path

        try:
            lesson = tmp_path / "2026-04-11_120000_lesson.md"
            lesson.write_text(
                "# Lesson\n\n"
                "**Goal:** Test\n\n"
                "## Improvements\n"
                "- Use better prompts\n"
            )

            summary = get_lessons_summary()
            assert "better prompts" in summary.lower()
        finally:
            self_improve.LESSONS_DIR = original


class TestOnRunComplete:
    def test_integration(self, tmp_path):
        import self_improve
        original = self_improve.LESSONS_DIR
        self_improve.LESSONS_DIR = tmp_path

        try:
            result = on_run_complete(
                goal="Test task",
                status="failed",
                steps_completed=1,
                steps_total=2,
                outputs=[{"success": False, "step": "step1", "tool_used": "run_shell", "error": "command not found"}],
                error="Test error",
            )
            assert result["success"] is False
            assert "lesson_file" in result
        finally:
            self_improve.LESSONS_DIR = original
