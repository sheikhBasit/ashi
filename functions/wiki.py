"""
Wiki operations for ASHI Second Brain.
BM25 search over markdown files. Index management. Lint.
Obsidian-compatible: uses [[wikilinks]] format.
Stdlib only — no external deps.
"""
import os
import re
from collections import Counter
from datetime import datetime


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\w+', text.lower())


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_len: int,
    avg_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    tf = Counter(doc_tokens)
    score = 0.0
    for token in query_tokens:
        if token not in tf:
            continue
        f = tf[token]
        score += (f * (k1 + 1)) / (f + k1 * (1 - b + b * doc_len / max(avg_len, 1)))
    return score


def search_wiki(query: str, wiki_path: str, top_k: int = 5) -> list[dict]:
    """BM25 search over all .md files under wiki_path."""
    wiki_path = os.path.expanduser(wiki_path)
    if not os.path.exists(wiki_path):
        return []

    docs = []
    for root, _, files in os.walk(wiki_path):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            tokens = _tokenize(content)
            docs.append({
                "file": fname,
                "path": fpath,
                "tokens": tokens,
                "content": content,
            })

    if not docs:
        return []

    query_tokens = _tokenize(query)
    avg_len = sum(len(d["tokens"]) for d in docs) / len(docs)
    scored = []
    for doc in docs:
        score = _bm25_score(
            query_tokens, doc["tokens"], len(doc["tokens"]), avg_len
        )
        if score > 0:
            scored.append({
                "file": doc["file"],
                "path": doc["path"],
                "score": round(score, 4),
                "snippet": doc["content"][:300],
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def update_index(wiki_path: str) -> None:
    """Rebuild wiki/index.md catalog from current .md files."""
    wiki_path = os.path.expanduser(wiki_path)
    index_path = os.path.join(wiki_path, "index.md")
    entries: list[str] = []

    for root, _, files in os.walk(wiki_path):
        for fname in sorted(files):
            if fname.endswith(".md") and fname not in ("index.md", "log.md"):
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, wiki_path)
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline().strip().lstrip("# ") or fname
                entries.append(f"- [{first_line}]({rel}) — auto-indexed")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# ASHI Wiki Index\n\n")
        f.write(f"> Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## All Pages\n\n")
        f.write("\n".join(entries) + "\n")


def append_wiki_log(
    log_path: str, event_type: str, title: str, detail: str = ""
) -> None:
    """Append one timestamped entry to the wiki log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"## [{timestamp}] {event_type} | {title}\n"
    if detail:
        line += f"- {detail}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def lint_wiki(wiki_path: str) -> dict:
    """Return orphan pages and basic health stats."""
    wiki_path = os.path.expanduser(wiki_path)
    all_pages: set[str] = set()
    linked_pages: set[str] = set()
    wikilink_re = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]*)?\]\]')

    for root, _, files in os.walk(wiki_path):
        for fname in files:
            if fname.endswith(".md") and fname not in ("index.md", "log.md"):
                page_name = fname[:-3]
                all_pages.add(page_name)
                fpath = os.path.join(root, fname)
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for m in wikilink_re.finditer(content):
                    linked_pages.add(m.group(1).strip())

    orphans = [
        {"file": p, "reason": "no inbound wikilinks"}
        for p in sorted(all_pages)
        if p not in linked_pages
    ]
    return {"orphans": orphans, "total_pages": len(all_pages)}
