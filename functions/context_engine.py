"""
context_engine.py -- Omniscient context engine for ASHI Vizier mode.

Polls all context sources every 30s and maintains a LiveContext object
that any agent or the Vizier loop can query.

Sources:
  - Active window + open files (xdotool / wmctrl)
  - Recent git commits (workspace repos)
  - System stats (psutil via monitor.py)
  - Second Brain daily notes + tasks
  - Google Calendar (optional, via API)
  - Recent agent conversations (from memory)

Runs as an asyncio background task inside ashi_daemon.py.
"""

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import psutil

logger = logging.getLogger("ashi.context_engine")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POLL_INTERVAL_S = int(os.getenv("ASHI_CONTEXT_POLL_S", "30"))
SECOND_BRAIN = Path(os.getenv("SECOND_BRAIN_PATH", os.path.expanduser("~/SecondBrain")))
WORKSPACE_DIRS = [
    Path(os.path.expanduser(p))
    for p in os.getenv("ASHI_WORKSPACE_DIRS", "~/workspace,~/Villaex").split(",")
    if p.strip()
]
MAX_RECENT_COMMITS = 10
MAX_RECENT_INTERACTIONS = 20


# ---------------------------------------------------------------------------
# LiveContext — the single source of truth for "what's happening now"
# ---------------------------------------------------------------------------
@dataclass
class LiveContext:
    """Snapshot of everything ASHI knows about the current moment."""

    # Desktop state
    active_window_title: str = ""
    active_window_class: str = ""
    active_window_pid: int = 0

    # Work context
    open_editors: list[str] = field(default_factory=list)
    recent_git_commits: list[dict] = field(default_factory=list)
    current_git_branch: str = ""
    current_git_repo: str = ""

    # System state
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    disk_percent: float = 0.0
    running_services: dict = field(default_factory=dict)

    # Second Brain
    today_focus: list[str] = field(default_factory=list)
    today_todos: list[str] = field(default_factory=list)
    today_completed: list[str] = field(default_factory=list)

    # Calendar (optional)
    upcoming_events: list[dict] = field(default_factory=list)

    # Recent interactions
    recent_interactions: list[dict] = field(default_factory=list)

    # Metadata
    last_updated: str = ""
    update_count: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self, max_length: int = 2000) -> str:
        """Compact text summary for injection into LLM prompts."""
        parts = []

        # Time
        now = datetime.now()
        parts.append(f"Time: {now.strftime('%Y-%m-%d %H:%M %A')}")

        # What Basit is doing
        if self.active_window_title:
            parts.append(f"Active window: {self.active_window_title}")
        if self.current_git_repo:
            parts.append(f"Working in: {self.current_git_repo} (branch: {self.current_git_branch})")

        # Recent commits
        if self.recent_git_commits:
            commits_str = "; ".join(
                f"{c.get('repo', '?')}: {c.get('message', '')[:60]}"
                for c in self.recent_git_commits[:3]
            )
            parts.append(f"Recent commits: {commits_str}")

        # System
        parts.append(
            f"System: CPU {self.cpu_percent}%, RAM {self.ram_percent}% "
            f"({self.ram_used_gb}GB), Disk {self.disk_percent}%"
        )

        # Services
        up_services = [k for k, v in self.running_services.items() if v.get("status") == "up"]
        if up_services:
            parts.append(f"Services up: {', '.join(up_services)}")

        # Today's focus
        if self.today_focus:
            parts.append(f"Today's focus: {'; '.join(self.today_focus)}")

        # Todos
        pending = [t for t in self.today_todos if t not in self.today_completed]
        if pending:
            parts.append(f"Pending todos ({len(pending)}): {'; '.join(pending[:5])}")

        # Calendar
        if self.upcoming_events:
            events_str = "; ".join(
                f"{e.get('time', '?')}: {e.get('title', '?')}"
                for e in self.upcoming_events[:3]
            )
            parts.append(f"Upcoming: {events_str}")

        text = "\n".join(parts)
        if len(text) > max_length:
            text = text[:max_length - 3] + "..."
        return text

    def to_dict(self) -> dict:
        """Full serializable dict."""
        return {
            "active_window_title": self.active_window_title,
            "active_window_class": self.active_window_class,
            "active_window_pid": self.active_window_pid,
            "open_editors": self.open_editors,
            "recent_git_commits": self.recent_git_commits,
            "current_git_branch": self.current_git_branch,
            "current_git_repo": self.current_git_repo,
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "ram_used_gb": self.ram_used_gb,
            "disk_percent": self.disk_percent,
            "running_services": self.running_services,
            "today_focus": self.today_focus,
            "today_todos": self.today_todos,
            "today_completed": self.today_completed,
            "upcoming_events": self.upcoming_events,
            "recent_interactions": self.recent_interactions,
            "last_updated": self.last_updated,
            "update_count": self.update_count,
        }


# ---------------------------------------------------------------------------
# Singleton context
# ---------------------------------------------------------------------------
_live_context = LiveContext()
_lock = asyncio.Lock()


def get_context() -> LiveContext:
    """Get the current LiveContext snapshot. Thread-safe read."""
    return _live_context


# ---------------------------------------------------------------------------
# Pollers — each collects one category of context
# ---------------------------------------------------------------------------

def _poll_active_window() -> dict:
    """Get active window info via xdotool."""
    result = {"title": "", "class": "", "pid": 0}
    try:
        wid = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=3,
        )
        if wid.returncode != 0:
            return result
        window_id = wid.stdout.strip()

        # Get window name
        name_proc = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=3,
        )
        if name_proc.returncode == 0:
            result["title"] = name_proc.stdout.strip()

        # Get window PID
        pid_proc = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowpid"],
            capture_output=True, text=True, timeout=3,
        )
        if pid_proc.returncode == 0:
            result["pid"] = int(pid_proc.stdout.strip())

        # Get window class via xprop
        xprop = subprocess.run(
            ["xprop", "-id", window_id, "WM_CLASS"],
            capture_output=True, text=True, timeout=3,
        )
        if xprop.returncode == 0 and "=" in xprop.stdout:
            result["class"] = xprop.stdout.split("=", 1)[1].strip().strip('"')

    except FileNotFoundError:
        # xdotool not installed or no X11 display
        pass
    except Exception as e:
        logger.debug("Active window poll failed: %s", e)
    return result


def _poll_open_editors() -> list[str]:
    """Find open editor windows (VS Code, Cursor, Neovim, etc.)."""
    editors = []
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            name = (proc.info.get("name") or "").lower()
            if name in ("code", "cursor", "nvim", "vim", "zed", "codium"):
                cmdline = proc.info.get("cmdline") or []
                # Extract file/folder args
                for arg in cmdline[1:]:
                    if not arg.startswith("-") and os.path.exists(arg):
                        editors.append(arg)
    except Exception as e:
        logger.debug("Editor poll failed: %s", e)
    return editors[:10]


def _poll_git_context() -> dict:
    """Get recent git activity from workspace directories."""
    commits = []
    current_repo = ""
    current_branch = ""

    for workspace in WORKSPACE_DIRS:
        if not workspace.is_dir():
            continue
        # Check if workspace itself is a git repo
        repos = []
        if (workspace / ".git").exists():
            repos.append(workspace)
        else:
            # Check one level deep
            try:
                for child in workspace.iterdir():
                    if child.is_dir() and (child / ".git").exists():
                        repos.append(child)
            except PermissionError:
                continue

        for repo in repos[:10]:  # cap to avoid scanning too many
            try:
                # Recent commits (last 24h)
                since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d")
                log_proc = subprocess.run(
                    ["git", "log", f"--since={since}", "--oneline", "-5",
                     "--format=%h|%s|%ai"],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(repo),
                )
                if log_proc.returncode == 0:
                    for line in log_proc.stdout.strip().splitlines():
                        parts = line.split("|", 2)
                        if len(parts) == 3:
                            commits.append({
                                "repo": repo.name,
                                "hash": parts[0],
                                "message": parts[1],
                                "date": parts[2],
                            })

                # Check if this repo has the most recent commit
                branch_proc = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True, text=True, timeout=3,
                    cwd=str(repo),
                )
                if branch_proc.returncode == 0 and branch_proc.stdout.strip():
                    # Use the repo with most recent activity
                    if commits and commits[-1].get("repo") == repo.name:
                        current_repo = repo.name
                        current_branch = branch_proc.stdout.strip()

            except Exception as e:
                logger.debug("Git poll failed for %s: %s", repo, e)

    # Sort by date descending
    commits.sort(key=lambda c: c.get("date", ""), reverse=True)
    return {
        "commits": commits[:MAX_RECENT_COMMITS],
        "current_repo": current_repo,
        "current_branch": current_branch,
    }


def _poll_system_stats() -> dict:
    """Quick system stats via psutil."""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_percent": cpu,
            "ram_percent": mem.percent,
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "disk_percent": disk.percent,
        }
    except Exception as e:
        logger.debug("System stats poll failed: %s", e)
        return {}


def _poll_services() -> dict:
    """Check key services. Lightweight — port checks only."""
    import socket

    services = {}
    checks = [
        ("ollama", "127.0.0.1", 11434),
        ("langfuse", "127.0.0.1", 3100),
        ("ashi_daemon", "127.0.0.1", 7070),
    ]
    for name, host, port in checks:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((host, port))
            sock.close()
            services[name] = {"status": "up" if result == 0 else "down"}
        except Exception:
            services[name] = {"status": "down"}
    return services


def _poll_daily_notes() -> dict:
    """Read today's daily note for focus/todos."""
    today = datetime.now().strftime("%Y-%m-%d")
    note_path = SECOND_BRAIN / "Daily" / f"{today}.md"

    result = {"focus": [], "todos": [], "completed": []}

    if not note_path.exists():
        return result

    try:
        content = note_path.read_text(encoding="utf-8")

        # Extract focus items
        in_focus = False
        in_todos = False
        for line in content.splitlines():
            stripped = line.strip()

            if stripped.startswith("## Focus"):
                in_focus = True
                in_todos = False
                continue
            elif stripped.startswith("## Todos") or stripped.startswith("## Tasks"):
                in_focus = False
                in_todos = True
                continue
            elif stripped.startswith("## "):
                in_focus = False
                in_todos = False
                continue

            if in_focus and stripped and stripped[0].isdigit():
                # "1. Do something"
                text = re.sub(r"^\d+\.\s*", "", stripped)
                if text:
                    result["focus"].append(text)

            if in_todos:
                if stripped.startswith("- [x]") or stripped.startswith("- [X]"):
                    text = re.sub(r"^-\s*\[[xX]\]\s*", "", stripped)
                    result["completed"].append(text)
                    result["todos"].append(text)
                elif stripped.startswith("- [ ]"):
                    text = re.sub(r"^-\s*\[\s\]\s*", "", stripped)
                    result["todos"].append(text)

    except Exception as e:
        logger.debug("Daily note parse failed: %s", e)

    return result


# ---------------------------------------------------------------------------
# Context Engine — background loop
# ---------------------------------------------------------------------------

async def _update_context_once() -> None:
    """Run all pollers and update the LiveContext."""
    global _live_context

    errors = []
    loop = asyncio.get_event_loop()

    # Run CPU-bound pollers in thread pool
    try:
        window = await loop.run_in_executor(None, _poll_active_window)
    except Exception as e:
        window = {"title": "", "class": "", "pid": 0}
        errors.append(f"window: {e}")

    try:
        editors = await loop.run_in_executor(None, _poll_open_editors)
    except Exception as e:
        editors = []
        errors.append(f"editors: {e}")

    try:
        git = await loop.run_in_executor(None, _poll_git_context)
    except Exception as e:
        git = {"commits": [], "current_repo": "", "current_branch": ""}
        errors.append(f"git: {e}")

    try:
        stats = await loop.run_in_executor(None, _poll_system_stats)
    except Exception as e:
        stats = {}
        errors.append(f"stats: {e}")

    try:
        services = await loop.run_in_executor(None, _poll_services)
    except Exception as e:
        services = {}
        errors.append(f"services: {e}")

    try:
        daily = await loop.run_in_executor(None, _poll_daily_notes)
    except Exception as e:
        daily = {"focus": [], "todos": [], "completed": []}
        errors.append(f"daily: {e}")

    # Update the shared context atomically
    async with _lock:
        ctx = _live_context
        ctx.active_window_title = window.get("title", "")
        ctx.active_window_class = window.get("class", "")
        ctx.active_window_pid = window.get("pid", 0)
        ctx.open_editors = editors
        ctx.recent_git_commits = git.get("commits", [])
        ctx.current_git_branch = git.get("current_branch", "")
        ctx.current_git_repo = git.get("current_repo", "")
        ctx.cpu_percent = stats.get("cpu_percent", 0.0)
        ctx.ram_percent = stats.get("ram_percent", 0.0)
        ctx.ram_used_gb = stats.get("ram_used_gb", 0.0)
        ctx.disk_percent = stats.get("disk_percent", 0.0)
        ctx.running_services = services
        ctx.today_focus = daily.get("focus", [])
        ctx.today_todos = daily.get("todos", [])
        ctx.today_completed = daily.get("completed", [])
        ctx.last_updated = datetime.now().isoformat()
        ctx.update_count += 1
        ctx.errors = errors


async def run_context_engine() -> None:
    """Main loop. Call this as an asyncio task from the daemon."""
    logger.info("Context engine starting (poll every %ds)", POLL_INTERVAL_S)

    while True:
        try:
            await _update_context_once()
            ctx = get_context()
            if ctx.update_count % 10 == 0:
                logger.info(
                    "Context update #%d: window=%s, repo=%s, cpu=%.0f%%",
                    ctx.update_count,
                    ctx.active_window_title[:40],
                    ctx.current_git_repo,
                    ctx.cpu_percent,
                )
        except Exception as e:
            logger.error("Context engine error: %s", e, exc_info=True)

        await asyncio.sleep(POLL_INTERVAL_S)


# ---------------------------------------------------------------------------
# Manual trigger for testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json

    logging.basicConfig(level=logging.DEBUG)

    async def _test():
        await _update_context_once()
        ctx = get_context()
        print(_json.dumps(ctx.to_dict(), indent=2, default=str))
        print("\n--- Summary ---")
        print(ctx.summary())

    asyncio.run(_test())
