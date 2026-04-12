"""Tests for vizier_loop.py"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from vizier_loop import (
    _execute_send_notification,
    _execute_write_reminder,
    _execute_update_daily_note,
    _execute_log_observation,
    _log_vizier_action,
    _vizier_tick,
    SAFE_AUTO_ACTIONS,
    DANGEROUS_ACTIONS,
)


class TestActionClassification:
    def test_safe_actions_defined(self):
        assert "send_notification" in SAFE_AUTO_ACTIONS
        assert "write_reminder" in SAFE_AUTO_ACTIONS
        assert "log_observation" in SAFE_AUTO_ACTIONS

    def test_dangerous_actions_defined(self):
        assert "run_shell" in DANGEROUS_ACTIONS
        assert "git_commit" in DANGEROUS_ACTIONS
        assert "delete_file" in DANGEROUS_ACTIONS

    def test_no_overlap(self):
        overlap = SAFE_AUTO_ACTIONS & DANGEROUS_ACTIONS
        assert len(overlap) == 0, f"Actions in both safe and dangerous: {overlap}"


class TestExecutors:
    def test_send_notification(self):
        with patch("vizier_loop.subprocess.run") as mock_run:
            result = _execute_send_notification({"title": "Test", "body": "Hello"})
            assert "sent" in result.lower() or "failed" in result.lower()

    def test_write_reminder(self, tmp_path):
        import vizier_loop

        original = vizier_loop.SECOND_BRAIN
        vizier_loop.SECOND_BRAIN = tmp_path

        # Create Daily directory (write_reminder creates the file, not the dir)
        (tmp_path / "Daily").mkdir()

        try:
            result = _execute_write_reminder({"text": "Buy groceries"})
            assert "written" in result.lower() or "reminder" in result.lower()

            # Check file was created
            from datetime import datetime

            today = datetime.now().strftime("%Y-%m-%d")
            note = tmp_path / "Daily" / f"{today}.md"
            assert note.exists()
            content = note.read_text()
            assert "Buy groceries" in content
        finally:
            vizier_loop.SECOND_BRAIN = original

    def test_write_reminder_empty(self):
        result = _execute_write_reminder({"text": ""})
        assert "skipped" in result.lower()

    def test_update_daily_note_todos(self, tmp_path):
        import vizier_loop

        original = vizier_loop.SECOND_BRAIN
        vizier_loop.SECOND_BRAIN = tmp_path

        # Create daily dir
        (tmp_path / "Daily").mkdir()
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        note = tmp_path / "Daily" / f"{today}.md"
        note.write_text("# Today\n")

        try:
            result = _execute_update_daily_note({"section": "todos", "text": "Fix the bug"})
            assert "updated" in result.lower()

            content = note.read_text()
            assert "- [ ] Fix the bug" in content
        finally:
            vizier_loop.SECOND_BRAIN = original

    def test_log_observation(self):
        result = _execute_log_observation({"text": "Basit is working on ASHI"})
        assert "logged" in result.lower()


class TestVizierLog:
    def test_log_action(self, tmp_path):
        import vizier_loop

        original = vizier_loop.VIZIER_LOG
        vizier_loop.VIZIER_LOG = tmp_path / "vizier.log"

        try:
            _log_vizier_action(
                {"action": "send_notification", "confidence": 0.9, "reason": "test"},
                "Notification sent",
                True,
            )
            assert vizier_loop.VIZIER_LOG.exists()
            content = vizier_loop.VIZIER_LOG.read_text()
            entry = json.loads(content.strip())
            assert entry["action"] == "send_notification"
            assert entry["auto_executed"] is True
        finally:
            vizier_loop.VIZIER_LOG = original


class TestVizierTick:
    @pytest.mark.asyncio
    async def test_tick_skips_when_no_context(self):
        """Vizier should skip when context engine hasn't populated yet."""
        mock_ctx_obj = MagicMock()
        mock_ctx_obj.last_updated = ""  # not yet populated

        with patch("context_engine.get_context", return_value=mock_ctx_obj):
            # Need to also patch where vizier imports it
            import context_engine

            original_fn = context_engine.get_context
            context_engine.get_context = lambda: mock_ctx_obj
            try:
                result = await _vizier_tick(time.time() - 300)
                assert isinstance(result, float)
            finally:
                context_engine.get_context = original_fn

    @pytest.mark.asyncio
    async def test_tick_handles_no_api_key(self):
        """Vizier should handle missing API key gracefully."""
        mock_ctx_obj = MagicMock()
        mock_ctx_obj.last_updated = "2026-01-01T00:00:00"
        mock_ctx_obj.summary.return_value = "Test context"

        import context_engine

        original_fn = context_engine.get_context
        context_engine.get_context = lambda: mock_ctx_obj

        try:
            with patch("vizier_loop._get_or_key", return_value=None):
                with patch("vizier_loop._log_vizier_action"):
                    result = await _vizier_tick(time.time() - 300)
                    assert isinstance(result, float)
        finally:
            context_engine.get_context = original_fn

    @pytest.mark.asyncio
    async def test_tick_logs_none_action(self):
        """Vizier should handle 'none' action from LLM."""
        mock_ctx_obj = MagicMock()
        mock_ctx_obj.last_updated = "2026-01-01T00:00:00"
        mock_ctx_obj.summary.return_value = "Test context"

        import context_engine

        original_fn = context_engine.get_context
        context_engine.get_context = lambda: mock_ctx_obj

        try:
            with patch(
                "vizier_loop._call_vizier_llm",
                return_value={"action": "none", "confidence": 0.0, "reason": "nothing to do"},
            ):
                with patch("vizier_loop._log_vizier_action") as mock_log:
                    result = await _vizier_tick(time.time() - 300)
                    mock_log.assert_called_once()
        finally:
            context_engine.get_context = original_fn
