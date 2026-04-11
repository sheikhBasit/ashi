# tests/test_host_agent.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from unittest.mock import patch
from host_agent import HostAgent, _merge_plans, _parse_steps
from blackboard import Blackboard


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_multi_brain(steps: list[str]):
    """Mock _plan_multi_brain to return a fixed list."""
    return patch.object(HostAgent, "_plan_multi_brain", return_value=steps)

def _mock_ollama(steps_text: str):
    return patch("host_agent._call_ollama", return_value=(steps_text, 100))


# ── HostAgent.plan ─────────────────────────────────────────────────────────────

def test_host_agent_returns_step_list():
    bb = Blackboard(goal="research ASHI and write a summary")
    agent = HostAgent()
    steps = ["Search wiki for ASHI", "Summarize findings", "Write output to file"]
    with _mock_multi_brain(steps):
        result = agent.plan(bb)
    assert len(result) == 3
    assert "Search wiki" in result[0]

def test_host_agent_falls_back_to_local_when_multi_brain_empty():
    bb = Blackboard(goal="do something")
    agent = HostAgent()
    fake_response = "1. Step one\n2. Step two\n3. Step three"
    with _mock_multi_brain([]), _mock_ollama(fake_response):
        steps = agent.plan(bb)
    assert len(steps) == 3
    assert not steps[0].startswith("1.")

def test_host_agent_caps_steps_at_max():
    bb = Blackboard(goal="do ten things", max_steps=3)
    agent = HostAgent()
    many_steps = [f"Step {i+1}" for i in range(10)]
    with _mock_multi_brain(many_steps):
        steps = agent.plan(bb)
    assert len(steps) <= 3

def test_host_agent_handles_all_empty():
    bb = Blackboard(goal="do something")
    agent = HostAgent()
    with _mock_multi_brain([]), _mock_ollama(""):
        steps = agent.plan(bb)
    assert steps == ["Complete the goal: do something"]


# ── _merge_plans ───────────────────────────────────────────────────────────────

def test_merge_plans_consensus_steps_first():
    plans = [
        ["Search wiki for ASHI", "Summarize results", "Write to file"],
        ["Search wiki for ASHI", "Run shell ls", "Write to file"],
        ["Search wiki for ASHI", "Check disk space"],
    ]
    merged = _merge_plans(plans, max_steps=10)
    # "Search wiki for ASHI" appears in all 3 — must be first
    assert "Search wiki for ASHI" in merged[0]

def test_merge_plans_deduplicates():
    plans = [
        ["Search wiki", "Search wiki", "Write output"],
        ["Search wiki", "Run shell"],
    ]
    merged = _merge_plans(plans, max_steps=10)
    # "search wiki" should appear only once
    normalised = [s.lower() for s in merged]
    assert normalised.count(next(s for s in normalised if "search wiki" in s)) == 1

def test_merge_plans_respects_max_steps():
    plans = [
        [f"Step {i}" for i in range(8)],
        [f"Step {i}" for i in range(8)],
    ]
    merged = _merge_plans(plans, max_steps=4)
    assert len(merged) <= 4

def test_merge_plans_empty_input():
    assert _merge_plans([], max_steps=5) == []


# ── _parse_steps ───────────────────────────────────────────────────────────────

def test_parse_steps_strips_numbering():
    raw = "1. Search wiki\n2. Run shell\n3. Write output"
    steps = _parse_steps(raw, 10)
    assert not steps[0].startswith("1.")
    assert "Search wiki" in steps[0]

def test_parse_steps_caps_at_max():
    raw = "\n".join(f"{i+1}. Step {i+1}" for i in range(10))
    steps = _parse_steps(raw, 3)
    assert len(steps) == 3
