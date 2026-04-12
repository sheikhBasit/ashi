"""
Integration test: full TCU round-trip without Claude.
Uses mocked Ollama calls so it runs offline.
Scenario: "Summarize what ASHI is and save to wiki"
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))

from intent import extract_intent
from tcu import TCU
from ingest_source import ingest_source
from update_entity import update_entity
from review_task import review_task
from run_skill import run_skill
from tool_dispatch import dispatch, extract_tool_calls, dispatch_all


MOCK_JUDGE_RESPONSE = json.dumps({
    "score": 9,
    "verdict": "pass",
    "notes": "Task completed correctly: ASHI entity created with accurate facts."
})

MOCK_SKILL_RESPONSE = (
    "# Research: ASHI\n\n## Summary\nASHI is a local AI operating system built on Ollama "
    "with BM25 wiki search and TCU-based task execution.\n\n## Key Facts\n"
    "- Local-first: uses deepseek-r1 and qwen3 models\n"
    "- Second Brain integration via Obsidian wiki\n"
    "- TCU checkpointing for crash recovery\n\n## Gaps\n"
    "- Phase 2 Tauri UI not yet implemented",
    150,  # tokens
)


def test_full_tcu_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_path = os.path.join(tmp, "wiki")
        tasks_path = os.path.join(tmp, "tasks")
        log_path = os.path.join(tmp, "logs")
        os.makedirs(wiki_path)
        os.makedirs(tasks_path)
        os.makedirs(log_path)

        # seed wiki with ASHI entry
        ingest_source(
            "ASHI is a local AI operating system built on Ollama and deepseek-r1.",
            label="ashi-seed",
            wiki_path=wiki_path,
        )

        # 1. extract intent
        intent = extract_intent("Summarize what ASHI is and save to wiki")
        assert "action" in intent  # intent extractor always returns an action

        # 2. create TCU
        tcu = TCU.create("Summarize ASHI and save to wiki", "ashi", tasks_path)
        tcu_id = tcu._data["id"]
        assert os.path.exists(os.path.join(tasks_path, "active", f"{tcu_id}.json"))

        # 3. run research skill (mocked)
        skills_path = os.path.join(os.path.dirname(__file__), "..", "skills")
        with patch("run_skill._call_ollama", return_value=MOCK_SKILL_RESPONSE):
            with patch("run_skill.LOG_PATH", log_path):
                skill_result = run_skill(
                    "research",
                    {"topic": "ASHI", "depth": "brief", "context": ""},
                    skills_path=skills_path,
                )
        assert "ASHI" in skill_result["output"]
        assert skill_result["tokens_used"] == 150

        # 4. update wiki entity from skill output
        facts = [
            "Local-first AI OS built on Ollama",
            "Uses deepseek-r1 planner and qwen3 executor",
            "TCU-based task execution with crash recovery",
        ]
        entity_result = update_entity("ASHI", "project", facts, wiki_path=wiki_path)
        assert entity_result["status"] == "ok"
        assert entity_result["facts_added"] == 3

        # 5. mark TCU done and judge it
        tcu.start_step(1, "research")
        tcu.complete_step(1, output=skill_result["output"])
        tcu.mark_done(judge_score=9.0)

        with patch("review_task._call_ollama", return_value=MOCK_JUDGE_RESPONSE):
            with patch("review_task.LOG_PATH", log_path):
                verdict = review_task(tcu_id, tasks_path=tasks_path)

        assert verdict["verdict"] == "pass"
        assert verdict["score"] >= 8

        # 6. verify TCU has judge stored (stays in active/ since mark_done doesn't move it)
        active_path = os.path.join(tasks_path, "active", f"{tcu_id}.json")
        with open(active_path) as f:
            tcu_data = json.load(f)
        assert tcu_data.get("judge", {}).get("verdict") == "pass"

        # 7. verify entity page exists on disk
        entity_page = os.path.join(wiki_path, "entities", "ashi.md")
        assert os.path.exists(entity_page)
        with open(entity_page) as f:
            content = f.read()
        assert "Local-first AI OS" in content


def test_tool_dispatch_round_trip(tmp_path):
    """Verify extract_tool_calls + dispatch works end-to-end."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "ashi.md").write_text("# ASHI\nLocal AI operating system.\n")

    llm_response = f'''
I need to search for information about ASHI.
```json
{{"tool": "search_wiki", "args": {{"query": "ASHI local AI", "wiki_path": "{wiki_dir}", "top_k": 2}}}}
```
Let me also check for orphan pages.
```json
{{"tool": "lint_wiki", "args": {{"wiki_path": "{wiki_dir}"}}}}
```
'''
    results = dispatch_all(llm_response)
    assert len(results) == 2
    # search_wiki returns a list wrapped in {"result": [...]}
    search_out = results[0]
    assert "result" in search_out or isinstance(search_out, list)
    # lint_wiki returns dict with orphans key
    lint_out = results[1]
    assert "orphans" in lint_out
