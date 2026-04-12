"""
run_shell — execute a shell command on the local machine and return output.
Used by tool_dispatch and the Tauri terminal panel.

Safety rules:
- Commands run as the current user (basitdev), no privilege escalation
- Timeout enforced (default 30s, max 120s)
- Working directory defaults to SecondBrain, can be overridden
- stdout + stderr both captured and returned
- Non-zero exit codes returned as result, not raised as exceptions
"""
import os
import subprocess

DEFAULT_CWD = os.path.expanduser("~/Desktop/SecondBrain")
MAX_TIMEOUT = 120


def run_shell(
    command: str,
    cwd: str = DEFAULT_CWD,
    timeout: int = 30,
    env_extra: dict | None = None,
) -> dict:
    """
    Run a shell command and return its output.

    Args:
        command:    Shell command string (passed to bash -c)
        cwd:        Working directory (default: SecondBrain)
        timeout:    Seconds before kill (max 120)
        env_extra:  Extra env vars to inject (merged with current env)

    Returns:
        {
          "stdout": str,
          "stderr": str,
          "exit_code": int,
          "command": str,
          "cwd": str,
          "timed_out": bool,
        }
    """
    timeout = min(int(timeout), MAX_TIMEOUT)
    cwd = os.path.expanduser(cwd)
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser("~")

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    timed_out = False
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        stdout = ""
        stderr = f"Command timed out after {timeout}s"
        exit_code = -1
        timed_out = True

    # Truncate very long outputs to avoid flooding context
    MAX_OUT = 8000
    if len(stdout) > MAX_OUT:
        stdout = stdout[:MAX_OUT] + f"\n... [truncated, {len(stdout)} chars total]"
    if len(stderr) > MAX_OUT:
        stderr = stderr[:MAX_OUT] + f"\n... [truncated, {len(stderr)} chars total]"

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "command": command,
        "cwd": cwd,
        "timed_out": timed_out,
    }
