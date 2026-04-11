# tests/test_agent_runner.py
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch
from agent_runner import run_agent, AgentResult

def _mock_plan(steps):
    return patch("agent_runner.HostAgent.plan", return_value=steps)

def _mock_step(result_dict):
    return patch("agent_runner.TaskAgent.execute_step", return_value=result_dict)

def test_run_agent_returns_agent_result():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["search wiki"]), \
             _mock_step({"success": True, "tool_used": "search_wiki", "output": "found stuff"}):
            result = run_agent("find ASHI info", tasks_path=tmpdir, require_confirmation=False)

    assert isinstance(result, AgentResult)
    assert result.goal == "find ASHI info"
    assert result.steps_completed >= 1

def test_run_agent_stops_at_budget():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["step 1", "step 2", "step 3", "step 4", "step 5"]), \
             _mock_step({"success": True, "tool_used": "search_wiki", "output": "ok"}):
            result = run_agent("do many things", max_steps=2, tasks_path=tmpdir, require_confirmation=False)

    assert result.steps_completed <= 2

def test_run_agent_pauses_on_confirmation_required():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["delete files"]), \
             _mock_step({
                 "success": False,
                 "tool_used": "run_shell",
                 "requires_confirmation": True,
                 "risk": "irreversible",
                 "pending_call": {"tool": "run_shell", "args": {"command": "rm -rf /tmp/x"}},
                 "error": "Action requires confirmation",
             }):
            result = run_agent("delete files", tasks_path=tmpdir, require_confirmation=True)

    assert result.status == "awaiting_confirmation"
    assert result.pending_confirmation is not None

def test_run_agent_detects_convergence():
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mock_plan(["step1", "step2", "step3"]), \
             _mock_step({"success": False, "tool_used": "run_shell", "error": "failed"}):
            result = run_agent("do stuff", tasks_path=tmpdir, require_confirmation=False, max_consecutive_failures=2)

    assert result.status in ("failed", "done")
    assert result.steps_completed <= 3
