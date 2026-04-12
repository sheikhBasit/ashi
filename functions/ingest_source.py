"""
ingest_source — fetch/read a source, chunk it, write to wiki, index in LanceDB.
No external deps beyond stdlib. LanceDB wrapped in try/except.
"""
import os
import re
import urllib.request
from datetime import datetime

WIKI_PATH = os.path.expanduser("~/Desktop/SecondBrain/wiki")
LOG_PATH = os.path.expanduser("~/Desktop/SecondBrain/wiki/log.md")
CHUNK_WORDS = 800


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


def _fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ASHI/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    # strip HTML tags
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _chunk_text(text: str, max_words: int = CHUNK_WORDS) -> list[str]:
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current_words: list[str] = []

    for para in paragraphs:
        words = para.split()
        if len(current_words) + len(words) > max_words and current_words:
            chunks.append(" ".join(current_words))
            current_words = []
        current_words.extend(words)

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks or [text[:4000]]


def _write_wiki_chunk(
    chunk: str, label: str, idx: int, wiki_path: str, date_str: str
) -> str:
    ingest_dir = os.path.join(wiki_path, "ingest")
    os.makedirs(ingest_dir, exist_ok=True)
    slug = _slug(label) if label else "source"
    fname = f"{date_str}-{slug}-{idx}.md"
    fpath = os.path.join(ingest_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(f"# {label or 'Ingested Source'} (chunk {idx + 1})\n")
        f.write(f"ingested:: {date_str}\n\n")
        f.write(chunk)
    return fpath


def _index_in_lancedb(chunk: str, path: str) -> None:
    try:
        import sys

        venv_site = os.path.expanduser(
            "~/Desktop/SecondBrain/Projects/ashi/.venv/lib/python3.12/site-packages"
        )
        if venv_site not in sys.path:
            sys.path.insert(0, venv_site)

        store_module_path = os.path.expanduser(
            "~/Desktop/SecondBrain/Projects/ashi/memory"
        )
        if store_module_path not in sys.path:
            sys.path.insert(0, store_module_path)

        from lancedb_store import VectorStore

        store = VectorStore()
        store.add(chunk, {"source": path})
    except Exception:
        pass  # LanceDB optional — BM25 search still works


def ingest_source(
    source: str, label: str = "", wiki_path: str = WIKI_PATH
) -> dict:
    """
    Fetch/read source, chunk, write wiki pages, index in LanceDB.

    Args:
        source: URL, file path, or raw text (auto-detected)
        label:  Human-readable name for the source
        wiki_path: Path to wiki directory

    Returns:
        {"status": "ok", "chunks": int, "wiki_files": list[str]}
    """
    wiki_path = os.path.expanduser(wiki_path)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- detect source type ---
    if source.startswith(("http://", "https://")):
        text = _fetch_url(source)
        if not label:
            label = source.split("/")[-1] or "web"
    elif os.path.exists(os.path.expanduser(source)):
        fpath = os.path.expanduser(source)
        with open(fpath, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        if not label:
            label = os.path.basename(fpath)
    else:
        text = source
        if not label:
            label = "raw-text"

    chunks = _chunk_text(text)
    wiki_files: list[str] = []

    for idx, chunk in enumerate(chunks):
        wf = _write_wiki_chunk(chunk, label, idx, wiki_path, date_str)
        wiki_files.append(wf)
        _index_in_lancedb(chunk, wf)

    # append to wiki log
    log_path = os.path.join(wiki_path, "log.md")
    if os.path.exists(log_path):
        try:
            from wiki import append_wiki_log

            append_wiki_log(log_path, "ingest", label, f"{len(chunks)} chunks")
        except Exception:
            pass

    return {"status": "ok", "chunks": len(chunks), "wiki_files": wiki_files}
