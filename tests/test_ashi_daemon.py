"""
Tests for ashi_daemon.py -- the ASHI HTTP daemon endpoints.
Uses FastAPI TestClient (httpx-backed, no real server needed).
"""

import sys
import os
import time
from unittest.mock import patch, MagicMock

import pytest

# Ensure functions/ is importable
_FUNCTIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions")
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

from fastapi.testclient import TestClient
from ashi_daemon import app, results


@pytest.fixture(autouse=True)
def _clear_results():
    """Clear the result store before each test."""
    results._store.clear()
    yield
    results._store.clear()


@pytest.fixture
def client():
    """FastAPI test client."""
    import ashi_daemon
    ashi_daemon._start_time = time.time()
    return TestClient(app)


# -------------------------------------------------------------------------
# GET /health
# -------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.2.0"
        assert "uptime" in data
        assert isinstance(data["ollama"], bool)

    def test_health_uptime_positive(self, client):
        resp = client.get("/health")
        assert resp.json()["uptime"] >= 0


# -------------------------------------------------------------------------
# GET /tools
# -------------------------------------------------------------------------


class TestTools:
    def test_tools_returns_list(self, client):
        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)
        # Should have at least a few tools from TOOL_REGISTRY
        assert len(data["tools"]) > 0

    def test_tools_have_name_and_description(self, client):
        resp = client.get("/tools")
        for tool in resp.json()["tools"]:
            assert "name" in tool
            assert "description" in tool


# -------------------------------------------------------------------------
# POST /tool/call
# -------------------------------------------------------------------------


class TestToolCall:
    def test_unknown_tool_returns_error(self, client):
        resp = client.post("/tool/call", json={"tool": "nonexistent_tool_xyz", "args": {}})
        assert resp.status_code == 200  # dispatch returns error in body, not HTTP error
        data = resp.json()
        assert "error" in data
        assert "unknown tool" in data["error"]

    def test_tool_call_missing_tool_field(self, client):
        resp = client.post("/tool/call", json={"args": {}})
        # Pydantic validation error -- tool is required
        assert resp.status_code == 422

    def test_tool_call_with_valid_tool(self, client):
        """Call list_skills which should work without external deps."""
        resp = client.post("/tool/call", json={"tool": "list_skills", "args": {"system": "all"}})
        assert resp.status_code == 200
        data = resp.json()
        # Should return a result (either skills list or error, but not crash)
        assert isinstance(data, dict)


# -------------------------------------------------------------------------
# POST /agent/run
# -------------------------------------------------------------------------


class TestAgentRun:
    @patch("ashi_daemon.run_agent")
    def test_agent_run_returns_tcu_id(self, mock_run, client):
        """Agent run should return immediately with a tcu_id."""
        mock_run.return_value = MagicMock(
            goal="test",
            status="done",
            steps_completed=1,
            steps_total=1,
            outputs=[],
            final_output="done",
            tcu_id=None,
            pending_confirmation=None,
            error=None,
            started_at="2024-01-01T00:00:00",
            finished_at="2024-01-01T00:00:01",
        )

        resp = client.post("/agent/run", json={"goal": "say hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "tcu_id" in data
        assert data["status"] == "running"
        assert len(data["tcu_id"]) > 0

    def test_agent_run_validation_max_steps(self, client):
        """max_steps must be 1-50."""
        resp = client.post("/agent/run", json={"goal": "test", "max_steps": 0})
        assert resp.status_code == 422

        resp = client.post("/agent/run", json={"goal": "test", "max_steps": 100})
        assert resp.status_code == 422

    def test_agent_run_missing_goal(self, client):
        resp = client.post("/agent/run", json={})
        assert resp.status_code == 422


# -------------------------------------------------------------------------
# GET /agent/status/{tcu_id}
# -------------------------------------------------------------------------


class TestAgentStatus:
    def test_status_not_found(self, client):
        resp = client.get("/agent/status/nonexistent-id")
        assert resp.status_code == 404

    def test_status_after_run(self, client):
        """After starting a run, status should be retrievable."""
        with patch("ashi_daemon.run_agent") as mock_run:
            mock_run.return_value = MagicMock(
                goal="test",
                status="done",
                steps_completed=1,
                steps_total=1,
                outputs=[],
                final_output="done",
                tcu_id=None,
                pending_confirmation=None,
                error=None,
                started_at="2024-01-01T00:00:00",
                finished_at="2024-01-01T00:00:01",
            )

            resp = client.post("/agent/run", json={"goal": "test goal"})
            tcu_id = resp.json()["tcu_id"]

            # Status should exist immediately (seeded as "running")
            resp2 = client.get(f"/agent/status/{tcu_id}")
            assert resp2.status_code == 200
            data = resp2.json()
            assert data["tcu_id"] == tcu_id
            assert data["goal"] == "test goal"
            # Could be "running" or "done" depending on timing
            assert data["status"] in ("running", "done", "failed")


# -------------------------------------------------------------------------
# POST /agent/confirm
# -------------------------------------------------------------------------


class TestAgentConfirm:
    def test_confirm_not_found(self, client):
        resp = client.post("/agent/confirm", json={"tcu_id": "nonexistent", "allow": True})
        assert resp.status_code == 404

    def test_confirm_wrong_status(self, client):
        """Cannot confirm a run that is not awaiting confirmation."""
        # Seed a "running" entry
        import asyncio

        async def _seed():
            await results.put("test-123", {
                "tcu_id": "test-123",
                "goal": "test",
                "status": "running",
            })

        asyncio.get_event_loop().run_until_complete(_seed())

        resp = client.post("/agent/confirm", json={"tcu_id": "test-123", "allow": True})
        assert resp.status_code == 400

    def test_confirm_awaiting(self, client):
        """Can confirm a run that is awaiting confirmation."""
        import asyncio

        async def _seed():
            await results.put("test-456", {
                "tcu_id": "test-456",
                "goal": "test",
                "status": "awaiting_confirmation",
            })

        asyncio.get_event_loop().run_until_complete(_seed())

        resp = client.post("/agent/confirm", json={"tcu_id": "test-456", "allow": True})
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    def test_deny_awaiting(self, client):
        """Can deny a run that is awaiting confirmation."""
        import asyncio

        async def _seed():
            await results.put("test-789", {
                "tcu_id": "test-789",
                "goal": "test",
                "status": "awaiting_confirmation",
            })

        asyncio.get_event_loop().run_until_complete(_seed())

        resp = client.post("/agent/confirm", json={"tcu_id": "test-789", "allow": False})
        assert resp.status_code == 200
        assert resp.json()["status"] == "denied"


# -------------------------------------------------------------------------
# ResultStore
# -------------------------------------------------------------------------


class TestResultStore:
    def test_bounded_eviction(self):
        """Store should evict oldest entries when full."""
        import asyncio
        from ashi_daemon import ResultStore

        store = ResultStore(maxsize=3)

        async def _fill():
            await store.put("a", {"id": "a"})
            await store.put("b", {"id": "b"})
            await store.put("c", {"id": "c"})
            await store.put("d", {"id": "d"})  # should evict "a"
            assert await store.get("a") is None
            assert await store.get("b") is not None
            assert await store.get("d") is not None

        asyncio.get_event_loop().run_until_complete(_fill())

    def test_update_status(self):
        """update_status should merge kwargs into existing entry."""
        import asyncio
        from ashi_daemon import ResultStore

        store = ResultStore()

        async def _test():
            await store.put("x", {"status": "running", "extra": "data"})
            await store.update_status("x", status="done", result="ok")
            entry = await store.get("x")
            assert entry["status"] == "done"
            assert entry["result"] == "ok"
            assert entry["extra"] == "data"

        asyncio.get_event_loop().run_until_complete(_test())
