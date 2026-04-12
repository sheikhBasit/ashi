import pytest
import tempfile
import os
from memory.lancedb_store import VectorStore
from memory.kuzu_graph import KnowledgeGraph

def test_vector_store_add_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(db_path=tmp)
        store.add(id="test-1", text="ASHI is a local AI OS", metadata={"type": "concept"})
        results = store.search("local AI operating system", top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "test-1"

def test_vector_store_empty_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(db_path=tmp)
        results = store.search("anything", top_k=5)
        assert results == []

def test_knowledge_graph_add_and_query():
    with tempfile.TemporaryDirectory() as tmp:
        graph = KnowledgeGraph(db_path=tmp)
        graph.add_entity("ASHI", entity_type="project", description="Local AI OS")
        graph.add_entity("Ollama", entity_type="tool", description="Local model server")
        graph.add_relationship("ASHI", "uses", "Ollama")
        neighbors = graph.get_neighbors("ASHI")
        assert "Ollama" in [n["name"] for n in neighbors]

def test_knowledge_graph_nonexistent_entity():
    with tempfile.TemporaryDirectory() as tmp:
        graph = KnowledgeGraph(db_path=tmp)
        neighbors = graph.get_neighbors("NonExistent")
        assert neighbors == []
