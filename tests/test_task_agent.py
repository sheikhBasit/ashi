# tests/test_task_agent.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch
from task_agent import TaskAgent
from blackboard import Blackboard
from action_classifier import ActionRisk

def _mock_executor(tool_json: str):
    return patch("task_agent._call_ollama", return_value=(tool_json, 50))

def _mock_dispatch(result: dict):
    return patch("task_agent.dispatch", return_value=result)

def test_task_agent_executes_reversible_tool():
    bb = Blackboard(goal="test")
    bb.set_plan(["Search wiki for ASHI"])
    agent = TaskAgent(require_confirmation=False)

    tool_response = '{"tool": "search_wiki", "args": {"query": "ASHI", "wiki_path": "~/Desktop/SecondBrain/wiki", "top_k": 3}}'
    dispatch_result = {"results": [{"snippet": "ASHI is a local AI OS"}]}

    with _mock_executor(tool_response), _mock_dispatch(dispatch_result):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is True
    assert "search_wiki" in result["tool_used"]

def test_task_agent_blocks_irreversible_without_confirmation():
    bb = Blackboard(goal="test")
    bb.set_plan(["Delete all temp files"])
    agent = TaskAgent(require_confirmation=True)

    tool_response = '{"tool": "run_shell", "args": {"command": "rm -rf /tmp/*"}}'

    with _mock_executor(tool_response):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is False
    assert result["requires_confirmation"] is True
    assert result["risk"] == ActionRisk.IRREVERSIBLE

def test_task_agent_handles_invalid_tool_json():
    bb = Blackboard(goal="test")
    bb.set_plan(["Do something"])
    agent = TaskAgent(require_confirmation=False)

    with _mock_executor("not valid json at all"):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is False
    assert "parse" in result["error"].lower() or "json" in result["error"].lower()

def test_task_agent_handles_dispatch_error():
    bb = Blackboard(goal="test")
    bb.set_plan(["Search wiki"])
    agent = TaskAgent(require_confirmation=False)

    tool_response = '{"tool": "search_wiki", "args": {"query": "test"}}'
    dispatch_error = {"error": "wiki not found", "tool": "search_wiki"}

    with _mock_executor(tool_response), _mock_dispatch(dispatch_error):
        result = agent.execute_step(bb, step_index=0)

    assert result["success"] is False
    assert "wiki not found" in result["error"]
