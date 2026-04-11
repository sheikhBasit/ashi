# tests/test_host_agent.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch
from host_agent import HostAgent
from blackboard import Blackboard

def _mock_ollama_response(steps_text: str):
    return patch(
        "host_agent._call_ollama",
        return_value=(steps_text, 100)
    )

def test_host_agent_returns_step_list():
    bb = Blackboard(goal="research ASHI and write a summary")
    agent = HostAgent()
    fake_response = "1. Search wiki for ASHI\n2. Summarize findings\n3. Write output to file"
    with _mock_ollama_response(fake_response):
        steps = agent.plan(bb)
    assert len(steps) == 3
    assert "Search wiki" in steps[0]

def test_host_agent_strips_numbering():
    bb = Blackboard(goal="do something")
    agent = HostAgent()
    fake_response = "1. Step one\n2. Step two\n3. Step three"
    with _mock_ollama_response(fake_response):
        steps = agent.plan(bb)
    assert not steps[0].startswith("1.")
    assert not steps[1].startswith("2.")

def test_host_agent_caps_steps_at_max():
    bb = Blackboard(goal="do ten things", max_steps=3)
    agent = HostAgent()
    fake_response = "\n".join(f"{i+1}. Step {i+1}" for i in range(10))
    with _mock_ollama_response(fake_response):
        steps = agent.plan(bb)
    assert len(steps) <= 3

def test_host_agent_handles_empty_response():
    bb = Blackboard(goal="do something")
    agent = HostAgent()
    with _mock_ollama_response(""):
        steps = agent.plan(bb)
    assert steps == ["Complete the goal: do something"]
