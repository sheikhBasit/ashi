"""
monitor.py — System monitor functions for ASHI.
Uses only stdlib + psutil (already in venv).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from typing import Optional

import psutil


def get_system_stats() -> dict:
    """CPU %, RAM used/total, disk used/total/percent for /, swap used/total."""
    cpu = psutil.cpu_percent(interval=0.2)

    mem = psutil.virtual_memory()
    ram_used_gb = round(mem.used / (1024 ** 3), 2)
    ram_total_gb = round(mem.total / (1024 ** 3), 2)
    ram_percent = mem.percent

    disk = psutil.disk_usage("/")
    disk_used_gb = round(disk.used / (1024 ** 3), 2)
    disk_total_gb = round(disk.total / (1024 ** 3), 2)
    disk_percent = disk.percent

    swap = psutil.swap_memory()
    swap_used_gb = round(swap.used / (1024 ** 3), 2)
    swap_total_gb = round(swap.total / (1024 ** 3), 2)

    return {
        "cpu_percent": cpu,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "ram_percent": ram_percent,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_percent": disk_percent,
        "swap_used_gb": swap_used_gb,
        "swap_total_gb": swap_total_gb,
    }


def get_processes(top_n: int = 15) -> list[dict]:
    """Top N processes by CPU: pid, name, cpu_percent, memory_mb, status."""
    procs = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
        try:
            info = proc.info
            mem_mb = round(info["memory_info"].rss / (1024 ** 2), 1) if info["memory_info"] else 0.0
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "",
                "cpu_percent": info["cpu_percent"] or 0.0,
                "memory_mb": mem_mb,
                "status": info["status"] or "",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    procs.sort(key=lambda p: p["cpu_percent"], reverse=True)
    return procs[:top_n]


def get_network_stats() -> dict:
    """bytes_sent, bytes_recv, packets_sent, packets_recv since boot."""
    net = psutil.net_io_counters()
    return {
        "bytes_sent": net.bytes_sent,
        "bytes_recv": net.bytes_recv,
        "packets_sent": net.packets_sent,
        "packets_recv": net.packets_recv,
        "bytes_sent_mb": round(net.bytes_sent / (1024 ** 2), 2),
        "bytes_recv_mb": round(net.bytes_recv / (1024 ** 2), 2),
    }


def _check_port(host: str, port: int, timeout: float = 1.0) -> Optional[float]:
    """
    Try connecting to host:port. Returns latency in ms if reachable, None otherwise.
    Uses socket.connect_ex — no HTTP calls.
    """
    import time

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    start = time.monotonic()
    result = sock.connect_ex((host, port))
    elapsed = (time.monotonic() - start) * 1000
    sock.close()
    if result == 0:
        return round(elapsed, 2)
    return None


def _check_docker() -> dict:
    """Check docker daemon by running `docker info` with a short timeout."""
    import time

    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=3,
        )
        elapsed = round((time.monotonic() - start) * 1000, 2)
        if proc.returncode == 0:
            return {"status": "up", "latency_ms": elapsed}
        return {"status": "down", "latency_ms": None}
    except Exception:
        return {"status": "down", "latency_ms": None}


def get_services() -> dict:
    """
    Check: ollama (port 11434), langfuse (port 3100), docker daemon.
    Each: {"status": "up"|"down", "latency_ms": float|None}
    """
    services: dict[str, dict] = {}

    # ollama
    latency = _check_port("127.0.0.1", 11434)
    services["ollama"] = {
        "status": "up" if latency is not None else "down",
        "latency_ms": latency,
    }

    # langfuse
    latency = _check_port("127.0.0.1", 3100)
    services["langfuse"] = {
        "status": "up" if latency is not None else "down",
        "latency_ms": latency,
    }

    # opencode — binary presence check
    opencode_bin = shutil.which("opencode") or os.path.expanduser("~/.opencode/bin/opencode")
    if os.path.isfile(opencode_bin):
        try:
            proc = subprocess.run(
                [opencode_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = proc.stdout.strip() or proc.stderr.strip()
            services["opencode"] = {"status": "up", "version": version, "latency_ms": None}
        except Exception:
            services["opencode"] = {"status": "down", "version": "", "latency_ms": None}
    else:
        services["opencode"] = {"status": "down", "version": "", "latency_ms": None}

    # docker — socket check on /var/run/docker.sock first, fallback CLI
    docker_sock = "/var/run/docker.sock"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            import time
            start = time.monotonic()
            result = sock.connect_ex(docker_sock)
            elapsed = round((time.monotonic() - start) * 1000, 2)
            if result == 0:
                services["docker"] = {"status": "up", "latency_ms": elapsed}
            else:
                services["docker"] = _check_docker()
    except Exception:
        services["docker"] = _check_docker()

    return services


def get_cron_jobs() -> list[dict]:
    """Parse crontab -l output. Return list of {schedule, command, last_run: None}."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        jobs = []
        for line in result.stdout.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 5)
            if len(parts) >= 6:
                schedule = " ".join(parts[:5])
                command = parts[5]
                jobs.append({
                    "schedule": schedule,
                    "command": command,
                    "last_run": None,
                })
            elif len(parts) >= 2:
                # @reboot style or short entries
                schedule = parts[0]
                command = " ".join(parts[1:])
                jobs.append({
                    "schedule": schedule,
                    "command": command,
                    "last_run": None,
                })
        return jobs
    except Exception:
        return []


def get_all() -> dict:
    """Return all stats in one call: {system, processes, network, services, crons, timestamp}."""
    return {
        "system": get_system_stats(),
        "processes": get_processes(top_n=15),
        "network": get_network_stats(),
        "services": get_services(),
        "crons": get_cron_jobs(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    print(json.dumps(get_all(), indent=2))
