"""Tests for telegram_bot.py — unit tests that don't require a real bot token."""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from telegram_bot import send_message, _check_authorized


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_without_bot_returns_false(self):
        """Should return False when bot not initialized."""
        import telegram_bot
        telegram_bot._bot_instance = None
        telegram_bot._chat_id = None

        result = await send_message("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_with_bot(self):
        """Should send message when bot is initialized."""
        import telegram_bot

        mock_bot = AsyncMock()
        telegram_bot._bot_instance = mock_bot
        telegram_bot._chat_id = 12345

        result = await send_message("Hello from test")
        assert result is True
        mock_bot.send_message.assert_called_once()

        # Cleanup
        telegram_bot._bot_instance = None
        telegram_bot._chat_id = None


class TestAuthorization:
    @pytest.mark.asyncio
    async def test_no_allowed_user_rejects(self):
        """Should reject when TELEGRAM_ALLOWED_USER_ID is 0."""
        with patch("telegram_bot.ALLOWED_USER_ID", 0):
            mock_update = MagicMock()
            mock_update.message = AsyncMock()
            mock_update.effective_user = MagicMock(id=999)

            result = await _check_authorized(mock_update)
            assert result is False

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        """Should reject unauthorized user."""
        with patch("telegram_bot.ALLOWED_USER_ID", 12345):
            mock_update = MagicMock()
            mock_update.message = AsyncMock()
            mock_update.effective_user = MagicMock(id=99999)

            result = await _check_authorized(mock_update)
            assert result is False

    @pytest.mark.asyncio
    async def test_authorized_user_accepted(self):
        """Should accept the authorized user."""
        with patch("telegram_bot.ALLOWED_USER_ID", 12345):
            mock_update = MagicMock()
            mock_update.effective_user = MagicMock(id=12345)

            result = await _check_authorized(mock_update)
            assert result is True


class TestRunTelegramBot:
    @pytest.mark.asyncio
    async def test_disabled_without_token(self):
        """Should exit immediately when no token set."""
        with patch("telegram_bot.BOT_TOKEN", ""):
            from telegram_bot import run_telegram_bot
            # Should return without error
            await run_telegram_bot()
