import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from tool_dispatch import dispatch, extract_tool_calls, list_tools, TOOL_REGISTRY


def test_dispatch_search_wiki(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "ashi.md").write_text("# ASHI\nLocal AI OS built on Ollama.\n")

    result = dispatch({
        "tool": "search_wiki",
        "args": {"query": "local AI", "wiki_path": str(wiki_dir), "top_k": 1},
    })
    assert isinstance(result, list) or isinstance(result, dict)
    # search_wiki returns a list — dispatch wraps non-dicts in {"result": ...}
    if isinstance(result, dict) and "result" in result:
        assert isinstance(result["result"], list)


def test_dispatch_unknown_tool():
    result = dispatch({"tool": "nonexistent_tool", "args": {}})
    assert "error" in result
    assert "available" in result


def test_dispatch_missing_tool_key():
    result = dispatch({"args": {}})
    assert "error" in result


def test_dispatch_bad_args():
    result = dispatch({"tool": "search_wiki", "args": "not a dict"})
    assert "error" in result


def test_extract_tool_calls_fenced():
    response = '''Let me search for this.
```json
{"tool": "search_wiki", "args": {"query": "ASHI", "wiki_path": "/tmp"}}
```
Done.'''
    calls = extract_tool_calls(response)
    assert len(calls) == 1
    assert calls[0]["tool"] == "search_wiki"


def test_extract_tool_calls_multiple():
    response = '''
```json
{"tool": "search_wiki", "args": {"query": "ASHI"}}
```
```json
{"tool": "lint_wiki", "args": {"wiki_path": "/tmp"}}
```
'''
    calls = extract_tool_calls(response)
    assert len(calls) == 2


def test_extract_tool_calls_no_tool_key():
    response = '```json\n{"key": "value"}\n```'
    calls = extract_tool_calls(response)
    assert calls == []


def test_list_tools():
    tools = list_tools()
    names = [t["name"] for t in tools]
    assert "search_wiki" in names
    assert "ingest_source" in names
    assert "run_skill" in names
    assert "tool_dispatch" not in names  # dispatch itself not in registry
