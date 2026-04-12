"""
memory_manager.py -- Three-tier memory for ASHI.

Tiers:
  Hot:  In-memory deque (current session, last N interactions). Instant.
  Warm: LanceDB vector store (semantic search over all past interactions). ~10ms.
  Cold: Google Drive sync (daily export). Archival.

Usage:
    from memory_manager import memory
    memory.remember("Basit decided to use LanceDB for vector search", {"type": "decision"})
    results = memory.recall("what database does ASHI use?", n=5)
    memory.remember_interaction("user", "How's the build going?")
    memory.remember_interaction("ashi", "All tests passing. 3 warnings in lint.")
"""

import hashlib
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ashi.memory")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MEMORY_DB_PATH = Path(os.getenv("ASHI_MEMORY_DB", os.path.expanduser("~/.ashi/memory_db")))
HOT_MEMORY_SIZE = int(os.getenv("ASHI_HOT_MEMORY_SIZE", "100"))
SECOND_BRAIN = Path(os.getenv("SECOND_BRAIN_PATH", os.path.expanduser("~/SecondBrain")))


# ---------------------------------------------------------------------------
# Hot memory — in-memory deque
# ---------------------------------------------------------------------------
@dataclass
class MemoryEntry:
    text: str
    role: str  # "user" | "ashi" | "system" | "observation"
    timestamp: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "role": self.role,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class HotMemory:
    """In-memory ring buffer for current session interactions."""

    def __init__(self, maxsize: int = HOT_MEMORY_SIZE):
        self._buffer: deque[MemoryEntry] = deque(maxlen=maxsize)

    def add(self, text: str, role: str = "system", metadata: Optional[dict] = None) -> None:
        entry = MemoryEntry(
            text=text,
            role=role,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        self._buffer.append(entry)

    def search(self, query: str, n: int = 5) -> list[dict]:
        """Simple keyword search over hot memory."""
        query_lower = query.lower()
        scored = []
        for entry in self._buffer:
            text_lower = entry.text.lower()
            # Simple relevance: count query word matches
            words = query_lower.split()
            score = sum(1 for w in words if w in text_lower)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e.to_dict() for _, e in scored[:n]]

    def recent(self, n: int = 10) -> list[dict]:
        """Get N most recent entries."""
        entries = list(self._buffer)
        return [e.to_dict() for e in entries[-n:]]

    def all_entries(self) -> list[dict]:
        return [e.to_dict() for e in self._buffer]

    @property
    def size(self) -> int:
        return len(self._buffer)


# ---------------------------------------------------------------------------
# Warm memory — LanceDB vector store
# ---------------------------------------------------------------------------
class WarmMemory:
    """LanceDB-backed semantic memory. Persists across restarts."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._store = None
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return

        self._db_path.mkdir(parents=True, exist_ok=True)

        try:
            # Reuse the existing VectorStore from memory/
            import sys
            ashi_root = Path(__file__).resolve().parent.parent
            memory_dir = ashi_root / "memory"
            if str(memory_dir) not in sys.path:
                sys.path.insert(0, str(memory_dir))

            from lancedb_store import VectorStore
            self._store = VectorStore(str(self._db_path), table_name="memories")
            self._initialized = True
            logger.info("Warm memory initialized at %s", self._db_path)

        except Exception as e:
            logger.error("Failed to initialize warm memory: %s", e)
            self._store = None
            self._initialized = True  # Don't retry every call

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        self._ensure_init()
        if not self._store:
            return

        meta = metadata or {}
        # Generate a deterministic ID from content + timestamp
        ts = datetime.now().isoformat()
        content_hash = hashlib.sha256(f"{ts}:{text}".encode()).hexdigest()[:12]
        entry_id = f"mem_{content_hash}"

        try:
            self._store.add(
                id=entry_id,
                text=text,
                metadata={"type": meta.get("type", "general")},
            )
        except Exception as e:
            logger.error("Warm memory add failed: %s", e)

    def search(self, query: str, n: int = 5) -> list[dict]:
        self._ensure_init()
        if not self._store:
            return []

        try:
            results = self._store.search(query, top_k=n)
            return [
                {
                    "text": r["text"],
                    "score": r.get("score", 0.0),
                    "source": "warm",
                }
                for r in results
            ]
        except Exception as e:
            logger.error("Warm memory search failed: %s", e)
            return []

    @property
    def is_available(self) -> bool:
        self._ensure_init()
        return self._store is not None


# ---------------------------------------------------------------------------
# MemoryManager — unified facade
# ---------------------------------------------------------------------------
class MemoryManager:
    """
    Unified memory interface. Queries hot first, then warm.
    Cold (Google Drive) is handled by gdrive_tool.py separately.
    """

    def __init__(
        self,
        hot_size: int = HOT_MEMORY_SIZE,
        db_path: Optional[Path] = None,
    ):
        self.hot = HotMemory(maxsize=hot_size)
        self.warm = WarmMemory(db_path or MEMORY_DB_PATH)
        self._session_start = datetime.now().isoformat()
        logger.info("MemoryManager initialized (hot=%d, warm=%s)", hot_size, db_path or MEMORY_DB_PATH)

    def remember(self, text: str, metadata: Optional[dict] = None) -> None:
        """Store a memory in both hot and warm tiers."""
        role = (metadata or {}).get("role", "system")
        self.hot.add(text, role=role, metadata=metadata)
        self.warm.add(text, metadata=metadata)

    def remember_interaction(self, role: str, text: str) -> None:
        """Store a conversation turn."""
        self.remember(text, metadata={"role": role, "type": "interaction"})

    def recall(self, query: str, n: int = 5) -> list[dict]:
        """
        Semantic recall. Checks hot memory first, then warm.
        Returns up to n results, deduplicated by text similarity.
        """
        results = []
        seen_texts = set()

        # Hot memory (keyword search, fast)
        hot_results = self.hot.search(query, n=n)
        for r in hot_results:
            text_key = r["text"][:100]
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                r["source"] = "hot"
                results.append(r)

        # Warm memory (semantic search)
        remaining = n - len(results)
        if remaining > 0:
            warm_results = self.warm.search(query, n=remaining + 3)  # fetch extra for dedup
            for r in warm_results:
                text_key = r["text"][:100]
                if text_key not in seen_texts:
                    seen_texts.add(text_key)
                    results.append(r)
                    if len(results) >= n:
                        break

        return results[:n]

    def recent(self, n: int = 10) -> list[dict]:
        """Get N most recent interactions from hot memory."""
        return self.hot.recent(n)

    def get_session_context(self, max_entries: int = 20) -> str:
        """Get a text summary of recent memory for prompt injection."""
        recent = self.hot.recent(max_entries)
        if not recent:
            return "No recent interactions."

        lines = []
        for entry in recent:
            role = entry.get("role", "system")
            text = entry.get("text", "")[:200]
            lines.append(f"[{role}] {text}")

        return "\n".join(lines)

    def flush_session_to_file(self) -> Optional[str]:
        """
        Write current session's hot memory to a Second Brain session file.
        Called on daemon shutdown or session end.
        """
        entries = self.hot.all_entries()
        if not entries:
            return None

        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        session_dir = SECOND_BRAIN / "AI" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / f"{timestamp}-ashi.md"

        lines = [
            f"# ASHI Session — {timestamp}",
            "",
            f"Session started: {self._session_start}",
            f"Entries: {len(entries)}",
            "",
            "## Interactions",
            "",
        ]

        for entry in entries:
            role = entry.get("role", "system")
            text = entry.get("text", "")
            ts = entry.get("timestamp", "")
            lines.append(f"### [{ts}] {role}")
            lines.append(text)
            lines.append("")

        session_file.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Session flushed to %s (%d entries)", session_file, len(entries))
        return str(session_file)

    def stats(self) -> dict:
        """Memory tier statistics."""
        return {
            "hot_size": self.hot.size,
            "hot_max": self.hot._buffer.maxlen,
            "warm_available": self.warm.is_available,
            "session_start": self._session_start,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
memory = MemoryManager()


# ---------------------------------------------------------------------------
# Tool functions (for tool_dispatch.py registration)
# ---------------------------------------------------------------------------

def tool_remember(text: str, memory_type: str = "general") -> dict:
    """Store a memory. Args: text (str), memory_type (str, default 'general')."""
    memory.remember(text, metadata={"type": memory_type})
    return {"status": "remembered", "text_preview": text[:100]}


def tool_recall(query: str, n: int = 5) -> dict:
    """Recall memories by semantic search. Args: query (str), n (int, default 5)."""
    results = memory.recall(query, n=n)
    return {"results": results, "count": len(results)}


def tool_memory_stats() -> dict:
    """Get memory tier statistics."""
    return memory.stats()


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Test hot memory
    memory.remember("ASHI uses LanceDB for vector search", {"type": "decision", "role": "system"})
    memory.remember("Basit prefers terminal-first workflow", {"type": "preference", "role": "system"})
    memory.remember_interaction("user", "What database does ASHI use?")
    memory.remember_interaction("ashi", "ASHI uses LanceDB for vector search and Kuzu for graph.")

    # Test recall
    results = memory.recall("database")
    print("Recall 'database':")
    for r in results:
        print(f"  [{r.get('source', '?')}] {r['text'][:80]}")

    # Test recent
    print("\nRecent:")
    for r in memory.recent(5):
        print(f"  [{r['role']}] {r['text'][:80]}")

    # Stats
    print(f"\nStats: {memory.stats()}")
