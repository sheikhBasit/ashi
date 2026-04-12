import pytest
import tempfile
import os
from functions.wiki import search_wiki, append_wiki_log, lint_wiki

def test_search_wiki_finds_content():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = os.path.join(tmp, "wiki")
        os.makedirs(wiki_dir)
        with open(os.path.join(wiki_dir, "ashi.md"), "w") as f:
            f.write("# ASHI\nASHI is a local AI operating system built on Ollama.\n")
        results = search_wiki("local AI operating system", wiki_path=wiki_dir, top_k=1)
        assert len(results) >= 1
        assert "ashi" in results[0]["file"].lower()

def test_search_wiki_empty():
    with tempfile.TemporaryDirectory() as tmp:
        results = search_wiki("anything", wiki_path=tmp, top_k=5)
        assert results == []

def test_append_wiki_log():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        log_path = f.name
        f.write("# Log\n\n")
    try:
        append_wiki_log(log_path, "ingest", "Test Article", "source ingested")
        with open(log_path) as f:
            content = f.read()
        assert "ingest" in content
        assert "Test Article" in content
    finally:
        os.unlink(log_path)

def test_lint_wiki_finds_orphans():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = os.path.join(tmp, "wiki")
        os.makedirs(wiki_dir)
        with open(os.path.join(wiki_dir, "page_a.md"), "w") as f:
            f.write("# Page A\nLinks to [[page_b]].\n")
        with open(os.path.join(wiki_dir, "page_b.md"), "w") as f:
            f.write("# Page B\nNo outbound links.\n")
        with open(os.path.join(wiki_dir, "orphan.md"), "w") as f:
            f.write("# Orphan\nNobody links here.\n")
        report = lint_wiki(wiki_dir)
        orphan_names = [o["file"] for o in report["orphans"]]
        assert any("orphan" in n for n in orphan_names)
