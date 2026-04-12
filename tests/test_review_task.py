import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from review_task import review_task, _parse_verdict, _load_tcu


def _make_tcu(tmp: str, intent: str = "test task", status: str = "done") -> str:
    import uuid
    tcu_id = f"test_{uuid.uuid4().hex[:6]}"
    done_dir = os.path.join(tmp, "done")
    os.makedirs(done_dir, exist_ok=True)
    data = {
        "id": tcu_id,
        "intent": intent,
        "status": status,
        "steps": [{"name": "step1", "status": "done", "output": "result text"}],
    }
    path = os.path.join(done_dir, f"{tcu_id}.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return tcu_id


def test_parse_verdict_pass():
    raw = '```json\n{"score": 9, "verdict": "pass", "notes": "well done"}\n```'
    v = _parse_verdict(raw)
    assert v["score"] == 9
    assert v["verdict"] == "pass"


def test_parse_verdict_with_think_tags():
    raw = '<think>let me think</think>\n{"score": 5, "verdict": "retry", "notes": "needs work"}'
    v = _parse_verdict(raw)
    assert v["verdict"] == "retry"
    assert v["score"] == 5


def test_parse_verdict_fail_fallback():
    v = _parse_verdict("this is garbage output")
    assert v["verdict"] == "fail"
    assert v["score"] == 0


def test_load_tcu_from_done():
    with tempfile.TemporaryDirectory() as tmp:
        tcu_id = _make_tcu(tmp)
        tcu = _load_tcu(tcu_id, tmp)
        assert tcu["id"] == tcu_id


def test_load_tcu_not_found():
    import pytest
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(FileNotFoundError):
            _load_tcu("nonexistent_id", tmp)


def test_review_task_mocked():
    with tempfile.TemporaryDirectory() as tmp:
        tcu_id = _make_tcu(tmp, intent="summarize ASHI")
        mock_response = '{"score": 8, "verdict": "pass", "notes": "task completed correctly"}'

        with patch("review_task._call_ollama", return_value=mock_response):
            with patch("review_task.LOG_PATH", tmp):
                result = review_task(tcu_id, tasks_path=tmp)

        assert result["verdict"] == "pass"
        assert result["score"] == 8
