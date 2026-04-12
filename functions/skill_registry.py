"""
skill_registry — read/write the unified ASHI skill registry.
Registry lives at skills/registry.json and maps skill names to handlers.
"""
import json
import os
from typing import Literal

REGISTRY_PATH = os.path.expanduser(
    "~/Desktop/SecondBrain/Projects/ashi/skills/registry.json"
)
SKILLS_PATH = os.path.expanduser("~/Desktop/SecondBrain/Projects/ashi/skills")
PLUGIN_CACHE = os.path.expanduser("~/.claude/plugins/cache")


def load_registry(registry_path: str = REGISTRY_PATH) -> dict:
    if not os.path.exists(registry_path):
        return {"_meta": {}, "skills": {}}
    with open(registry_path) as f:
        return json.load(f)


def save_registry(registry: dict, registry_path: str = REGISTRY_PATH) -> None:
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)


def get_skill(name: str, registry_path: str = REGISTRY_PATH) -> dict | None:
    reg = load_registry(registry_path)
    return reg["skills"].get(name)


def list_skills(
    system: Literal["ollama", "claude", "all"] = "all",
    registry_path: str = REGISTRY_PATH,
) -> list[dict]:
    reg = load_registry(registry_path)
    skills = [{"name": k, **v} for k, v in reg["skills"].items()]
    if system == "all":
        return skills
    return [s for s in skills if s.get("system") == system]
