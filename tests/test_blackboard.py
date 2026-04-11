# tests/test_blackboard.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from blackboard import Blackboard

def test_blackboard_stores_goal():
    bb = Blackboard(goal="research ASHI")
    assert bb.goal == "research ASHI"

def test_blackboard_set_plan():
    bb = Blackboard(goal="test")
    bb.set_plan(["step 1", "step 2"])
    assert bb.plan == ["step 1", "step 2"]
    assert bb.total_steps == 2

def test_blackboard_record_step_result():
    bb = Blackboard(goal="test")
    bb.set_plan(["do thing"])
    bb.record_result(0, "thing done", success=True)
    assert bb.results[0]["output"] == "thing done"
    assert bb.results[0]["success"] is True

def test_blackboard_step_budget():
    bb = Blackboard(goal="test", max_steps=5)
    assert bb.steps_remaining == 5
    bb.set_plan(["a", "b", "c"])
    bb.record_result(0, "ok", success=True)
    assert bb.steps_remaining == 4

def test_blackboard_is_done_when_all_steps_complete():
    bb = Blackboard(goal="test")
    bb.set_plan(["a", "b"])
    bb.record_result(0, "ok", success=True)
    bb.record_result(1, "ok", success=True)
    assert bb.is_done is True

def test_blackboard_to_dict_roundtrip():
    bb = Blackboard(goal="test")
    bb.set_plan(["a"])
    bb.record_result(0, "out", success=True)
    d = bb.to_dict()
    assert d["goal"] == "test"
    assert len(d["results"]) == 1
