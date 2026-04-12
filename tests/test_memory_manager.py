"""Tests for memory_manager.py"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from memory_manager import MemoryManager, HotMemory


class TestHotMemory:
    def test_add_and_recent(self):
        hot = HotMemory(maxsize=10)
        hot.add("first message", role="user")
        hot.add("second message", role="ashi")

        recent = hot.recent(5)
        assert len(recent) == 2
        assert recent[0]["text"] == "first message"
        assert recent[1]["text"] == "second message"

    def test_maxsize_eviction(self):
        hot = HotMemory(maxsize=3)
        for i in range(5):
            hot.add(f"message {i}")

        assert hot.size == 3
        recent = hot.recent(10)
        assert recent[0]["text"] == "message 2"  # oldest surviving
        assert recent[-1]["text"] == "message 4"  # newest

    def test_search_keyword(self):
        hot = HotMemory(maxsize=10)
        hot.add("ASHI uses LanceDB for vectors")
        hot.add("Basit prefers terminal workflow")
        hot.add("LanceDB is embedded and fast")

        results = hot.search("LanceDB")
        assert len(results) >= 2
        assert "LanceDB" in results[0]["text"]

    def test_search_no_match(self):
        hot = HotMemory(maxsize=10)
        hot.add("hello world")
        results = hot.search("nonexistent query xyz")
        assert results == []

    def test_all_entries(self):
        hot = HotMemory(maxsize=10)
        hot.add("a")
        hot.add("b")
        entries = hot.all_entries()
        assert len(entries) == 2


class TestMemoryManager:
    def test_remember_and_recall_hot(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db"))
        mm.remember("Python is great for scripting", {"type": "knowledge"})
        mm.remember("TypeScript for frontend", {"type": "knowledge"})

        results = mm.recall("Python scripting")
        assert len(results) >= 1
        assert any("Python" in r["text"] for r in results)

    def test_remember_interaction(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db2"))
        mm.remember_interaction("user", "What time is it?")
        mm.remember_interaction("ashi", "It is 3pm.")

        recent = mm.recent(5)
        assert len(recent) == 2
        assert recent[0]["role"] == "user"
        assert recent[1]["role"] == "ashi"

    def test_get_session_context(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db3"))
        mm.remember_interaction("user", "Build the context engine")
        mm.remember_interaction("ashi", "Context engine built and tested")

        ctx = mm.get_session_context()
        assert "user" in ctx
        assert "ashi" in ctx
        assert "context engine" in ctx.lower()

    def test_get_session_context_empty(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db4"))
        ctx = mm.get_session_context()
        assert "No recent interactions" in ctx

    def test_stats(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db5"))
        mm.remember("test")
        stats = mm.stats()
        assert stats["hot_size"] >= 1
        assert stats["hot_max"] == 50
        assert "session_start" in stats

    def test_flush_session_to_file(self, tmp_path):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db6"))
        mm.remember_interaction("user", "Test interaction")

        import memory_manager

        original = memory_manager.SECOND_BRAIN
        memory_manager.SECOND_BRAIN = tmp_path
        try:
            result = mm.flush_session_to_file()
            assert result is not None
            assert Path(result).exists()
            content = Path(result).read_text()
            assert "Test interaction" in content
        finally:
            memory_manager.SECOND_BRAIN = original

    def test_flush_empty_session(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db7"))
        result = mm.flush_session_to_file()
        assert result is None

    def test_deduplication_in_recall(self):
        mm = MemoryManager(hot_size=50, db_path=Path("/tmp/ashi_test_memory_db8"))
        # Add same text multiple times
        mm.remember("ASHI uses LanceDB")
        mm.remember("ASHI uses LanceDB")

        results = mm.recall("LanceDB", n=5)
        # Should not have exact duplicates in hot results
        texts = [r["text"][:100] for r in results if r.get("source") == "hot"]
        # At most 1 from hot (dedup)
        assert len(texts) <= 1
