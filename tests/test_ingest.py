import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from ingest_source import ingest_source, _chunk_text, _slug


def test_ingest_raw_text():
    with tempfile.TemporaryDirectory() as tmp:
        result = ingest_source("ASHI is a local AI operating system.", label="test", wiki_path=tmp)
        assert result["status"] == "ok"
        assert result["chunks"] >= 1
        assert len(result["wiki_files"]) >= 1
        assert os.path.exists(result["wiki_files"][0])


def test_ingest_creates_wiki_page():
    with tempfile.TemporaryDirectory() as tmp:
        text = "This is a test document about ASHI.\n\nIt has multiple paragraphs."
        result = ingest_source(text, label="ashi-test", wiki_path=tmp)
        fpath = result["wiki_files"][0]
        with open(fpath) as f:
            content = f.read()
        assert "ashi-test" in content.lower() or "Ingested" in content
        assert "ingested::" in content


def test_ingest_file():
    with tempfile.TemporaryDirectory() as tmp:
        src_file = os.path.join(tmp, "source.txt")
        with open(src_file, "w") as f:
            f.write("File content for ingestion test.\n")
        result = ingest_source(src_file, label="file-test", wiki_path=tmp)
        assert result["status"] == "ok"
        assert result["chunks"] == 1


def test_chunk_text_large():
    # chunker splits on \n\n paragraph boundaries — give it multiple paragraphs
    para = " ".join(["word"] * 300)
    text = "\n\n".join([para] * 8)  # 8 paragraphs × 300 words = 2400 words total
    chunks = _chunk_text(text, max_words=800)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.split()) <= 900  # tolerance for paragraph boundary rounding


def test_slug():
    assert _slug("Hello World!") == "hello-world"
    assert _slug("ASHI v0.1") == "ashi-v0-1"
