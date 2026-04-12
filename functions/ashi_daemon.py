#!/usr/bin/env python3
"""
ashi_daemon.py -- ASHI AI OS HTTP daemon.
FastAPI server on localhost:7070. Runs agents asynchronously, exposes tools, health checks.
Starts context engine, vizier loop, and telegram bot as background tasks.
Designed to run as a systemd user service.
"""

# ---------------------------------------------------------------------------
# PATH FIX: Python auto-adds the script's directory (functions/) to sys.path[0].
# functions/secrets.py shadows stdlib secrets, breaking starlette imports.
# Move functions/ to the END of sys.path so stdlib always wins.
# ---------------------------------------------------------------------------
import os
import sys

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.abspath(sys.path[0]) == _FUNCTIONS_DIR:
    sys.path.pop(0)
    if _FUNCTIONS_DIR not in sys.path:
        sys.path.append(_FUNCTIONS_DIR)
elif _FUNCTIONS_DIR not in sys.path:
    sys.path.append(_FUNCTIONS_DIR)

import asyncio
import logging
import signal
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent_runner import AgentResult, run_agent
from tool_dispatch import dispatch, list_tools

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DAEMON_HOST = os.getenv("ASHI_HOST", "127.0.0.1")
DAEMON_PORT = int(os.getenv("ASHI_PORT", "7070"))
MAX_RESULTS = 100
VERSION = "0.3.0"  # Vizier upgrade

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.path.expanduser("~/SecondBrain/AI/agent-logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "daemon.log"

logger = logging.getLogger("ashi_daemon")
logger.setLevel(logging.INFO)

_file_handler = logging.FileHandler(LOG_FILE)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_console_handler)

# ---------------------------------------------------------------------------
# In-memory result store (bounded OrderedDict, FIFO eviction)
# ---------------------------------------------------------------------------

class ResultStore:
    """Thread-safe bounded store for agent run results."""

    def __init__(self, maxsize: int = MAX_RESULTS):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._maxsize = maxsize
        self._lock = asyncio.Lock()

    async def put(self, tcu_id: str, data: dict) -> None:
        async with self._lock:
            self._store[tcu_id] = data
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    async def get(self, tcu_id: str) -> Optional[dict]:
        async with self._lock:
            return self._store.get(tcu_id)

    async def update_status(self, tcu_id: str, **kwargs) -> None:
        async with self._lock:
            if tcu_id in self._store:
                self._store[tcu_id].update(kwargs)


results = ResultStore()
_start_time: float = 0.0
_executor = ThreadPoolExecutor(max_workers=4)

# Background task handles (for clean shutdown)
_background_tasks: list[asyncio.Task] = []

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentRunRequest(BaseModel):
    goal: str
    max_steps: int = Field(default=10, ge=1, le=50)
    require_confirmation: bool = True


class AgentConfirmRequest(BaseModel):
    tcu_id: str
    allow: bool


class ToolCallRequest(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime: float
    ollama: bool
    context_engine: bool
    vizier: bool
    telegram: bool


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.time()
    logger.info("ASHI daemon starting on %s:%d (version %s)", DAEMON_HOST, DAEMON_PORT, VERSION)

    # Start background subsystems
    _start_background_tasks()

    yield

    # Clean shutdown
    logger.info("ASHI daemon shutting down gracefully")

    # Flush memory session
    try:
        from memory_manager import memory
        session_file = memory.flush_session_to_file()
        if session_file:
            logger.info("Session flushed to %s", session_file)
    except Exception as e:
        logger.warning("Session flush failed: %s", e)

    # Cancel background tasks
    for task in _background_tasks:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    _executor.shutdown(wait=False)


def _start_background_tasks():
    """Start context engine, vizier loop, and telegram bot as asyncio tasks."""

    # Context Engine
    try:
        from context_engine import run_context_engine
        task = asyncio.create_task(run_context_engine())
        task.set_name("context_engine")
        _background_tasks.append(task)
        logger.info("Context engine started as background task")
    except Exception as e:
        logger.error("Failed to start context engine: %s", e)

    # Vizier Loop
    try:
        from vizier_loop import run_vizier_loop
        task = asyncio.create_task(run_vizier_loop())
        task.set_name("vizier_loop")
        _background_tasks.append(task)
        logger.info("Vizier loop started as background task")
    except Exception as e:
        logger.error("Failed to start vizier loop: %s", e)

    # Telegram Bot
    try:
        from telegram_bot import run_telegram_bot
        task = asyncio.create_task(run_telegram_bot())
        task.set_name("telegram_bot")
        _background_tasks.append(task)
        logger.info("Telegram bot started as background task")
    except Exception as e:
        logger.error("Failed to start telegram bot: %s", e)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ASHI Daemon",
    version=VERSION,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _handle_sigterm(signum, frame):
    logger.info("Received SIGTERM — initiating clean shutdown")
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Helper: run agent in background thread
# ---------------------------------------------------------------------------

async def _run_agent_background(tcu_id: str, goal: str, max_steps: int, require_confirmation: bool):
    """Run the agent loop in the thread pool and store the result."""
    loop = asyncio.get_event_loop()

    # Record interaction in memory
    try:
        from memory_manager import memory
        memory.remember_interaction("user", goal)
    except Exception:
        pass

    try:
        result: AgentResult = await loop.run_in_executor(
            _executor,
            lambda: run_agent(
                goal=goal,
                max_steps=max_steps,
                require_confirmation=require_confirmation,
            ),
        )
        result_dict = asdict(result)
        result_dict["tcu_id"] = tcu_id
        await results.put(tcu_id, result_dict)
        logger.info("Agent run %s finished: status=%s steps=%d", tcu_id, result.status, result.steps_completed)

        # Self-improvement: evaluate run
        try:
            from self_improve import on_run_complete
            on_run_complete(
                goal=goal,
                status=result.status,
                steps_completed=result.steps_completed,
                steps_total=result.steps_total,
                outputs=result_dict.get("outputs", []),
                error=result.error,
            )
        except Exception as e:
            logger.debug("Self-improvement eval failed: %s", e)

        # Record result in memory
        try:
            from memory_manager import memory
            memory.remember_interaction("ashi", result.final_output or f"Completed: {result.status}")
        except Exception:
            pass

    except Exception as exc:
        error_result = {
            "tcu_id": tcu_id,
            "goal": goal,
            "status": "failed",
            "error": str(exc),
            "steps_completed": 0,
            "steps_total": 0,
            "outputs": [],
            "final_output": "",
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        }
        await results.put(tcu_id, error_result)
        logger.error("Agent run %s crashed: %s", tcu_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/agent/run")
async def agent_run(req: AgentRunRequest):
    """Start an agent run asynchronously. Returns immediately with tcu_id."""
    tcu_id = str(uuid.uuid4())[:12]
    logger.info("Starting agent run %s: goal=%r max_steps=%d", tcu_id, req.goal[:80], req.max_steps)

    # Seed the store with a running status
    await results.put(tcu_id, {
        "tcu_id": tcu_id,
        "goal": req.goal,
        "status": "running",
        "steps_completed": 0,
        "steps_total": 0,
        "outputs": [],
        "final_output": "",
        "error": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    })

    # Fire and forget
    asyncio.create_task(
        _run_agent_background(tcu_id, req.goal, req.max_steps, req.require_confirmation)
    )

    return {"tcu_id": tcu_id, "status": "running"}


@app.post("/agent/confirm")
async def agent_confirm(req: AgentConfirmRequest):
    """Resume a paused agent awaiting confirmation."""
    stored = await results.get(req.tcu_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Run {req.tcu_id} not found")

    if stored.get("status") != "awaiting_confirmation":
        raise HTTPException(
            status_code=400,
            detail=f"Run {req.tcu_id} is not awaiting confirmation (status={stored.get('status')})",
        )

    # For now, record the confirmation decision. Full resume requires agent loop refactoring.
    await results.update_status(
        req.tcu_id,
        status="confirmed" if req.allow else "denied",
        confirmation_decision={"allow": req.allow, "decided_at": datetime.now().isoformat()},
    )
    logger.info("Agent run %s confirmation: allow=%s", req.tcu_id, req.allow)

    return {"tcu_id": req.tcu_id, "status": "confirmed" if req.allow else "denied"}


@app.get("/agent/status/{tcu_id}")
async def agent_status(tcu_id: str):
    """Get the status of a running or completed agent run."""
    stored = await results.get(tcu_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Run {tcu_id} not found")
    return stored


@app.post("/tool/call")
async def tool_call(req: ToolCallRequest):
    """Direct tool call bypassing the agent loop."""
    logger.info("Direct tool call: %s(%s)", req.tool, list(req.args.keys()))
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor,
        lambda: dispatch({"tool": req.tool, "args": req.args}),
    )
    return result


@app.get("/health")
async def health():
    """Health check with uptime, services, and subsystem status."""
    import shutil

    ollama_running = False
    ollama_bin = shutil.which("ollama")
    if ollama_bin:
        try:
            import subprocess
            proc = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                timeout=3,
            )
            ollama_running = proc.returncode == 0
        except Exception:
            pass

    # Check background task health
    context_alive = any(t.get_name() == "context_engine" and not t.done() for t in _background_tasks)
    vizier_alive = any(t.get_name() == "vizier_loop" and not t.done() for t in _background_tasks)
    telegram_alive = any(t.get_name() == "telegram_bot" and not t.done() for t in _background_tasks)

    return HealthResponse(
        status="ok",
        version=VERSION,
        uptime=round(time.time() - _start_time, 2),
        ollama=ollama_running,
        context_engine=context_alive,
        vizier=vizier_alive,
        telegram=telegram_alive,
    )


@app.get("/context")
async def get_live_context():
    """Get current LiveContext snapshot."""
    try:
        from context_engine import get_context
        ctx = get_context()
        return ctx.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context engine error: {e}")


@app.get("/context/summary")
async def get_context_summary():
    """Get compact text summary of current context."""
    try:
        from context_engine import get_context
        ctx = get_context()
        return {"summary": ctx.summary(), "last_updated": ctx.last_updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context engine error: {e}")


@app.get("/memory/stats")
async def memory_stats():
    """Get memory tier statistics."""
    try:
        from memory_manager import memory
        return memory.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory error: {e}")


@app.get("/memory/recent")
async def memory_recent(n: int = 10):
    """Get N most recent memory entries."""
    try:
        from memory_manager import memory
        return {"entries": memory.recent(n)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory error: {e}")


@app.get("/tools")
async def tools_list():
    """List all registered tools."""
    return {"tools": list_tools()}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Load .env if present
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
            logger.info("Loaded .env from %s", env_path)
        except ImportError:
            # Manual fallback
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ[key.strip()] = val.strip()

    uvicorn.run(
        app,
        host=DAEMON_HOST,
        port=DAEMON_PORT,
        log_level="info",
        access_log=False,
    )
