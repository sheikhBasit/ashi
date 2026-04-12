"""
Tests for skill_registry.py and sync_plugin_skills.py
"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))

from skill_registry import load_registry, save_registry, get_skill, list_skills
from sync_plugin_skills import (
    _parse_frontmatter,
    _is_wrapper_eligible,
    _generate_wrapper,
    _discover_ollama_skills,
    sync,
    WRAPPER_ELIGIBLE,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_skills_dir(tmp_path):
    """A temp skills/ dir with two native Ollama skills."""
    (tmp_path / "skills").mkdir()
    sd = tmp_path / "skills"

    (sd / "research.md").write_text(
        "---\nname: research\nversion: 1\nauthor: claude\nmodel_hint: executor\n---\n\n"
        "## System\nYou are a researcher.\n\n## User Template\nTopic: {topic}\n\n## Output Format\n# Research\n"
    )
    (sd / "code.md").write_text(
        "---\nname: code\nversion: 1\nauthor: claude\nmodel_hint: executor\n---\n\n"
        "## System\nYou write code.\n\n## User Template\nSpec: {spec}\n\n## Output Format\n```python\n```\n"
    )
    return sd


@pytest.fixture
def tmp_registry(tmp_path):
    """A temp registry.json with a few pre-seeded skills."""
    reg = {
        "_meta": {"schema_version": 1, "ollama_count": 2, "claude_count": 1},
        "skills": {
            "research": {"system": "ollama", "path": "/skills/research.md", "invoke": "run_skill"},
            "code": {"system": "ollama", "path": "/skills/code.md", "invoke": "run_skill"},
            "frontend-design": {
                "system": "claude", "plugin": "frontend-design",
                "path": "/cache/frontend-design/SKILL.md", "invoke": "claude_session",
                "description": "Production UI design",
            },
        },
    }
    rp = tmp_path / "registry.json"
    rp.write_text(json.dumps(reg))
    return str(rp)


# ── skill_registry tests ──────────────────────────────────────────────────────

class TestLoadSave:
    def test_load_missing_returns_empty(self, tmp_path):
        result = load_registry(str(tmp_path / "nonexistent.json"))
        assert result == {"_meta": {}, "skills": {}}

    def test_save_and_reload(self, tmp_path):
        rp = str(tmp_path / "reg.json")
        data = {"_meta": {"v": 1}, "skills": {"foo": {"system": "ollama"}}}
        save_registry(data, rp)
        loaded = load_registry(rp)
        assert loaded["skills"]["foo"]["system"] == "ollama"

    def test_save_creates_valid_json(self, tmp_path):
        rp = str(tmp_path / "reg.json")
        save_registry({"_meta": {}, "skills": {}}, rp)
        raw = json.loads(open(rp).read())
        assert "skills" in raw


class TestGetSkill:
    def test_get_existing(self, tmp_registry):
        entry = get_skill("research", tmp_registry)
        assert entry is not None
        assert entry["system"] == "ollama"

    def test_get_missing_returns_none(self, tmp_registry):
        assert get_skill("nonexistent", tmp_registry) is None

    def test_get_claude_skill(self, tmp_registry):
        entry = get_skill("frontend-design", tmp_registry)
        assert entry["system"] == "claude"
        assert entry["plugin"] == "frontend-design"


class TestListSkills:
    def test_list_all(self, tmp_registry):
        skills = list_skills("all", tmp_registry)
        assert len(skills) == 3
        names = {s["name"] for s in skills}
        assert "research" in names
        assert "frontend-design" in names

    def test_list_ollama_only(self, tmp_registry):
        skills = list_skills("ollama", tmp_registry)
        assert all(s["system"] == "ollama" for s in skills)
        assert len(skills) == 2

    def test_list_claude_only(self, tmp_registry):
        skills = list_skills("claude", tmp_registry)
        assert all(s["system"] == "claude" for s in skills)
        assert len(skills) == 1

    def test_each_skill_has_name(self, tmp_registry):
        for s in list_skills("all", tmp_registry):
            assert "name" in s


# ── sync_plugin_skills tests ──────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_parses_standard(self):
        content = "---\nname: test\nversion: 2\n---\n## Body\nHello"
        meta, body = _parse_frontmatter(content)
        assert meta["name"] == "test"
        assert meta["version"] == "2"
        assert "## Body" in body

    def test_no_frontmatter(self):
        content = "Just a body"
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == "Just a body"

    def test_description_extracted(self):
        content = "---\nname: foo\ndescription: Does something cool\n---\nbody"
        meta, _ = _parse_frontmatter(content)
        assert meta["description"] == "Does something cool"


class TestWrapperEligibility:
    def test_eligible_with_structure(self):
        content = "No tool signals\n1. Step one\n2. Step two\n3. Step three"
        assert _is_wrapper_eligible(content) is True

    def test_ineligible_with_tool_signal(self):
        content = "Use the Skill tool\n1. Step one\n2. Step two\n3. Step three"
        assert _is_wrapper_eligible(content) is False

    def test_ineligible_mcp_signal(self):
        content = "Call mcp__server\n1. a\n2. b\n3. c"
        assert _is_wrapper_eligible(content) is False

    def test_ineligible_no_structure(self):
        content = "Just some prose without numbered steps or phases"
        assert _is_wrapper_eligible(content) is False

    def test_phase_headers_count_as_structure(self):
        content = "## Phase 1\nDo this\n## Phase 2\nDo that\n## Phase 3\nVerify"
        assert _is_wrapper_eligible(content) is True


class TestGenerateWrapper:
    def test_generates_valid_frontmatter(self):
        content = "---\nname: test-skill\ndescription: A test skill\n---\n## Overview\nDo things systematically.\n1. Check\n2. Fix\n3. Verify"
        result = _generate_wrapper("test-skill", content, "A test skill")
        assert "---" in result
        assert "name: test-skill" in result
        assert "model_hint: executor" in result
        assert "author: claude-plugin-wrapper" in result

    def test_generates_three_sections(self):
        content = "## Overview\nBe systematic.\n1. Phase A\n2. Phase B\n3. Phase C"
        result = _generate_wrapper("my-skill", content, "desc")
        assert "## System" in result
        assert "## User Template" in result
        assert "## Output Format" in result

    def test_contains_task_template_var(self):
        content = "## Overview\nDo things.\n1. a\n2. b\n3. c"
        result = _generate_wrapper("skill", content, "desc")
        assert "{task}" in result

    def test_source_references_plugin(self):
        content = "## Overview\nX\n1. a\n2. b"
        result = _generate_wrapper("debug", content, "desc")
        assert "source: claude-plugin/debug" in result


class TestDiscoverOllamaSkills:
    def test_finds_md_files(self, tmp_skills_dir):
        skills = _discover_ollama_skills(str(tmp_skills_dir))
        assert "research" in skills
        assert "code" in skills

    def test_skill_has_system_ollama(self, tmp_skills_dir):
        skills = _discover_ollama_skills(str(tmp_skills_dir))
        assert skills["research"]["system"] == "ollama"

    def test_skill_has_correct_model_hint(self, tmp_skills_dir):
        skills = _discover_ollama_skills(str(tmp_skills_dir))
        assert skills["research"]["model_hint"] == "executor"

    def test_ignores_registry_json(self, tmp_skills_dir):
        (tmp_skills_dir / "registry.json").write_text('{"skills":{}}')
        skills = _discover_ollama_skills(str(tmp_skills_dir))
        assert "registry" not in skills


class TestSync:
    def _patch_sync(self, sps, tmp_sd, tmp_cache):
        """Patch sync module globals and return originals for restore."""
        orig = (sps.SKILLS_PATH, sps.PLUGIN_CACHE, sps.REGISTRY_PATH, sps.WRAPPERS_PATH)
        sps.SKILLS_PATH = str(tmp_sd)
        sps.PLUGIN_CACHE = str(tmp_cache)
        sps.REGISTRY_PATH = str(tmp_sd / "registry.json")
        sps.WRAPPERS_PATH = str(tmp_sd / "claude-wrappers")
        return orig

    def _restore_sync(self, sps, orig):
        sps.SKILLS_PATH, sps.PLUGIN_CACHE, sps.REGISTRY_PATH, sps.WRAPPERS_PATH = orig

    def test_sync_produces_registry(self, tmp_path):
        """Sync with empty plugin cache produces registry with at least ollama skills."""
        import functions.sync_plugin_skills as sps

        sd = tmp_path / "skills"
        sd.mkdir()
        (sd / "test-skill.md").write_text(
            "---\nname: test-skill\nversion: 1\nauthor: claude\nmodel_hint: executor\n---\n\n"
            "## System\nYou test.\n\n## User Template\nTask: {task}\n\n## Output Format\n# Result\n"
        )
        empty_cache = tmp_path / "cache"
        empty_cache.mkdir()

        orig = self._patch_sync(sps, sd, empty_cache)
        try:
            result = sps.sync()
            assert result["status"] == "ok"
            assert result["ollama_skills"] >= 1
            assert os.path.exists(str(sd / "registry.json"))
        finally:
            self._restore_sync(sps, orig)

    def test_dry_run_does_not_write(self, tmp_path):
        import functions.sync_plugin_skills as sps

        sd = tmp_path / "skills"
        sd.mkdir()
        empty_cache = tmp_path / "cache"
        empty_cache.mkdir()

        orig = self._patch_sync(sps, sd, empty_cache)
        try:
            result = sps.sync(dry_run=True)
            assert result["dry_run"] is True
            assert not (sd / "registry.json").exists()
        finally:
            self._restore_sync(sps, orig)
