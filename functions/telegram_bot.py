"""
telegram_bot.py -- Telegram bot for ASHI remote communication.

Features:
  - Receive text commands from Basit's phone -> dispatch to ASHI agent
  - Send proactive messages from ASHI -> Basit's phone
  - Authorized user only (TELEGRAM_ALLOWED_USER_ID)

Runs as an asyncio task inside ashi_daemon.py (polling mode, no webhook needed).

Requires: python-telegram-bot>=21.0

Setup:
  1. Message @BotFather on Telegram, create a bot, get token
  2. Set TELEGRAM_BOT_TOKEN=<token>
  3. Set TELEGRAM_ALLOWED_USER_ID=<your numeric user ID>
     (Message @userinfobot to get your ID)
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("ashi.telegram")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))
ASHI_DAEMON_URL = os.getenv("ASHI_DAEMON_URL", "http://127.0.0.1:7070")


# ---------------------------------------------------------------------------
# Singleton bot instance for sending messages from other modules
# ---------------------------------------------------------------------------
_bot_instance = None
_chat_id: Optional[int] = None


async def send_message(text: str) -> bool:
    """
    Send a message to Basit via Telegram.
    Can be called from anywhere (vizier_loop, context_engine, etc).
    Returns True if sent successfully.
    """
    global _bot_instance, _chat_id

    if not _bot_instance or not _chat_id:
        logger.debug("Telegram bot not initialized or no chat_id, cannot send")
        return False

    try:
        await _bot_instance.send_message(
            chat_id=_chat_id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Telegram message sent: %s", text[:80])
        return True
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


def send_message_sync(text: str) -> bool:
    """Synchronous wrapper for send_message. For use from non-async code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule it on the running loop
            future = asyncio.run_coroutine_threadsafe(send_message(text), loop)
            return future.result(timeout=10)
        else:
            return asyncio.run(send_message(text))
    except Exception as e:
        logger.error("Sync telegram send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Bot handlers
# ---------------------------------------------------------------------------

async def _check_authorized(update) -> bool:
    """Check if the message is from the authorized user."""
    if not ALLOWED_USER_ID:
        logger.warning("TELEGRAM_ALLOWED_USER_ID not set -- rejecting all messages")
        if update.message:
            await update.message.reply_text(
                "ASHI is not configured to accept messages. Set TELEGRAM_ALLOWED_USER_ID."
            )
        return False

    user_id = update.effective_user.id if update.effective_user else 0
    if user_id != ALLOWED_USER_ID:
        logger.warning("Unauthorized Telegram user: %d", user_id)
        if update.message:
            await update.message.reply_text("Unauthorized. This is a private bot.")
        return False

    return True


async def _handle_start(update, context) -> None:
    """Handle /start command."""
    if not await _check_authorized(update):
        return

    global _chat_id
    _chat_id = update.effective_chat.id

    await update.message.reply_text(
        "ASHI online. Send me any task and I'll handle it.\n\n"
        "Commands:\n"
        "/status - System status\n"
        "/context - What I know right now\n"
        "/memory - Search my memory\n"
        "/backup - Backup SecondBrain to Drive\n"
        "Or just type a task."
    )


async def _handle_status(update, context) -> None:
    """Handle /status command."""
    if not await _check_authorized(update):
        return

    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{ASHI_DAEMON_URL}/health", timeout=5.0)
            data = resp.json()
            text = (
                f"*ASHI Status*\n"
                f"Version: {data.get('version', '?')}\n"
                f"Uptime: {data.get('uptime', 0):.0f}s\n"
                f"Ollama: {'up' if data.get('ollama') else 'down'}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Cannot reach ASHI daemon: {e}")


async def _handle_context(update, context) -> None:
    """Handle /context command -- show current LiveContext."""
    if not await _check_authorized(update):
        return

    try:
        from context_engine import get_context
        ctx = get_context()
        summary = ctx.summary()
        await update.message.reply_text(f"```\n{summary}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Context unavailable: {e}")


async def _handle_memory(update, context) -> None:
    """Handle /memory <query> -- search ASHI memory."""
    if not await _check_authorized(update):
        return

    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /memory <search query>")
        return

    try:
        from memory_manager import memory
        results = memory.recall(query, n=5)
        if not results:
            await update.message.reply_text("No memories found.")
            return

        lines = ["*Memory Search Results:*\n"]
        for i, r in enumerate(results, 1):
            source = r.get("source", "?")
            text = r.get("text", "")[:200]
            lines.append(f"{i}. [{source}] {text}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Memory search failed: {e}")


async def _handle_backup(update, context) -> None:
    """Handle /backup -- trigger SecondBrain backup to Google Drive."""
    if not await _check_authorized(update):
        return

    await update.message.reply_text("Starting SecondBrain backup to Google Drive...")

    try:
        from gdrive_tool import gdrive_backup_second_brain

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, gdrive_backup_second_brain)

        if "error" in result:
            await update.message.reply_text(f"Backup failed: {result['error']}")
        else:
            await update.message.reply_text(
                f"Backup complete!\n"
                f"File: {result.get('name', '?')}\n"
                f"Size: {result.get('size_mb', '?')} MB\n"
                f"ID: {result.get('file_id', '?')}"
            )
    except Exception as e:
        await update.message.reply_text(f"Backup error: {e}")


async def _handle_message(update, context) -> None:
    """Handle any text message -- dispatch to ASHI agent."""
    if not await _check_authorized(update):
        return

    global _chat_id
    _chat_id = update.effective_chat.id

    text = update.message.text
    if not text or not text.strip():
        return

    logger.info("Telegram task from Basit: %s", text[:100])

    # Store interaction in memory
    try:
        from memory_manager import memory
        memory.remember_interaction("user_telegram", text)
    except Exception:
        pass

    await update.message.reply_text("Got it. Working on it...")

    # Dispatch to ASHI daemon
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ASHI_DAEMON_URL}/agent/run",
                json={"goal": text, "max_steps": 10, "require_confirmation": False},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            tcu_id = data.get("tcu_id", "?")

            await update.message.reply_text(f"Agent started (id: {tcu_id}). Polling for result...")

            # Poll for completion
            for _ in range(60):  # max 5 min
                await asyncio.sleep(5)
                try:
                    status_resp = await client.get(
                        f"{ASHI_DAEMON_URL}/agent/status/{tcu_id}",
                        timeout=5.0,
                    )
                    status_data = status_resp.json()
                    status = status_data.get("status", "unknown")

                    if status in ("completed", "done", "success"):
                        output = status_data.get("final_output", "Done.")
                        # Telegram max message length is 4096
                        if len(output) > 4000:
                            output = output[:4000] + "... (truncated)"
                        await update.message.reply_text(output)
                        return

                    if status in ("failed", "error", "denied"):
                        error = status_data.get("error", "Unknown error")
                        await update.message.reply_text(f"Task failed: {error}")
                        return

                    if status == "awaiting_confirmation":
                        await update.message.reply_text(
                            "Task needs confirmation. Check the ASHI dashboard."
                        )
                        return

                except Exception:
                    continue

            await update.message.reply_text("Task still running. Check ASHI dashboard for results.")

    except httpx.ConnectError:
        await update.message.reply_text("ASHI daemon is offline.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ---------------------------------------------------------------------------
# Bot startup
# ---------------------------------------------------------------------------

async def run_telegram_bot() -> None:
    """
    Start the Telegram bot with polling.
    Call this as an asyncio task from ashi_daemon.py.
    """
    if not BOT_TOKEN:
        logger.info("Telegram bot disabled (TELEGRAM_BOT_TOKEN not set)")
        return

    try:
        from telegram import Update
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except ImportError:
        logger.error(
            "python-telegram-bot not installed. "
            "Run: pip install python-telegram-bot"
        )
        return

    global _bot_instance

    logger.info("Starting Telegram bot (polling mode)")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", _handle_start))
    app.add_handler(CommandHandler("status", _handle_status))
    app.add_handler(CommandHandler("context", _handle_context))
    app.add_handler(CommandHandler("memory", _handle_memory))
    app.add_handler(CommandHandler("backup", _handle_backup))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    # Store bot instance for send_message()
    _bot_instance = app.bot

    # Start polling (this blocks until stopped)
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        logger.info("Telegram bot started. Waiting for messages.")

        # Keep running until cancelled
        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("Telegram bot shutting down")
    except Exception as e:
        logger.error("Telegram bot error: %s", e, exc_info=True)
    finally:
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN environment variable first.")
        print("Get a token from @BotFather on Telegram.")
    else:
        print(f"Starting bot with token {BOT_TOKEN[:10]}...")
        asyncio.run(run_telegram_bot())
