import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from update_entity import update_entity, _parse_existing_facts, _slug


def test_create_entity():
    with tempfile.TemporaryDirectory() as tmp:
        result = update_entity("ASHI", "project", ["Local AI OS", "Built on Ollama"], wiki_path=tmp)
        assert result["status"] == "ok"
        assert result["facts_added"] == 2
        assert result["facts_total"] == 2
        assert os.path.exists(result["path"])


def test_update_existing_entity():
    with tempfile.TemporaryDirectory() as tmp:
        update_entity("ASHI", "project", ["Local AI OS"], wiki_path=tmp)
        result = update_entity("ASHI", "project", ["Built on Ollama", "Uses BM25"], wiki_path=tmp)
        assert result["facts_added"] == 2
        assert result["facts_total"] == 3


def test_dedup_facts():
    with tempfile.TemporaryDirectory() as tmp:
        update_entity("ASHI", "project", ["Local AI OS", "Built on Ollama"], wiki_path=tmp)
        result = update_entity("ASHI", "project", ["Local AI OS"], wiki_path=tmp)
        assert result["facts_added"] == 0
        assert result["facts_total"] == 2


def test_entity_page_format():
    with tempfile.TemporaryDirectory() as tmp:
        update_entity("Test Entity", "tool", ["Does things"], wiki_path=tmp)
        slug = _slug("Test Entity")
        page = os.path.join(tmp, "entities", f"{slug}.md")
        with open(page) as f:
            content = f.read()
        assert "# Test Entity" in content
        assert "type:: tool" in content
        assert "updated::" in content
        assert "## Facts" in content
        assert "- Does things" in content


def test_parse_existing_facts():
    content = "# Entity\ntype:: tool\n\n## Facts\n- fact one\n- fact two\n\n## Other\nstuff\n"
    facts = _parse_existing_facts(content)
    assert facts == ["fact one", "fact two"]
