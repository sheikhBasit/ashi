# tests/test_action_classifier.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from action_classifier import classify_action, ActionRisk

def test_shell_delete_is_irreversible():
    risk = classify_action("run_shell", {"command": "rm -rf /tmp/test"})
    assert risk == ActionRisk.IRREVERSIBLE

def test_shell_read_is_reversible():
    risk = classify_action("run_shell", {"command": "ls /home"})
    assert risk == ActionRisk.REVERSIBLE

def test_search_wiki_is_reversible():
    risk = classify_action("search_wiki", {"query": "ASHI"})
    assert risk == ActionRisk.REVERSIBLE

def test_ingest_source_is_irreversible():
    risk = classify_action("ingest_source", {"url": "http://example.com"})
    assert risk == ActionRisk.IRREVERSIBLE

def test_update_entity_is_irreversible():
    risk = classify_action("update_entity", {"entity_name": "ASHI"})
    assert risk == ActionRisk.IRREVERSIBLE

def test_run_skill_is_reversible():
    risk = classify_action("run_skill", {"skill_name": "research"})
    assert risk == ActionRisk.REVERSIBLE

def test_unknown_tool_defaults_to_irreversible():
    risk = classify_action("unknown_future_tool", {})
    assert risk == ActionRisk.IRREVERSIBLE
