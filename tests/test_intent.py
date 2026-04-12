import pytest
import tempfile
import os
from functions.intent import extract_intent, append_intent_log, parse_intent_log

def test_extract_intent_simple():
    result = extract_intent("build a login page for villaex")
    assert result["action"] in ["build", "create", "implement", "add", "make", "write", "generate"]
    assert result["raw"] == "build a login page for villaex"

def test_extract_intent_fix():
    result = extract_intent("fix the bug where agent crashes on empty wiki")
    assert result["mode"] == "fix"

def test_append_and_parse_intent_log():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        log_path = f.name
        f.write("# Intent Log\n\n")
    try:
        append_intent_log(log_path=log_path, intent="build login feature", outcome="pending")
        entries = parse_intent_log(log_path)
        assert len(entries) == 1
        assert entries[0]["intent"] == "build login feature"
        assert entries[0]["outcome"] == "pending"
    finally:
        os.unlink(log_path)
