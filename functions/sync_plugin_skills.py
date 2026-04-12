"""
sync_plugin_skills — discover Claude plugin SKILL.md files, index them in registry.json,
and generate Ollama-compatible wrapper skills for eligible process-oriented skills.

Usage:
    python -m functions.sync_plugin_skills
    python -m functions.sync_plugin_skills --check-mtime   # skip if nothing changed
    python -m functions.sync_plugin_skills --dry-run       # show what would change
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone

SKILLS_PATH = os.path.expanduser("~/Desktop/SecondBrain/Projects/ashi/skills")
WRAPPERS_PATH = os.path.join(SKILLS_PATH, "claude-wrappers")
PLUGIN_CACHE = os.path.expanduser("~/.claude/plugins/cache")
REGISTRY_PATH = os.path.join(SKILLS_PATH, "registry.json")

# Claude plugin skills eligible for Ollama wrappers: processual, model-agnostic,
# no tool calls, content fits qwen3:0.6b context. All others stay Claude-only.
WRAPPER_ELIGIBLE = {
    "systematic-debugging",
    "test-driven-development",
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "verification-before-completion",
}

# Signals that a skill depends on Claude tools/MCPs — disqualifies from wrapping
TOOL_SIGNALS = [
    "Skill tool", "mcp__", "gh pr", "TaskCreate", "WebFetch",
    "browser_", "Agent tool", "TodoWrite", "ExitPlanMode",
]


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter. Returns (meta_dict, body_without_frontmatter)."""
    meta: dict = {}
    m = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                meta[k.strip()] = v.strip()
        body = content[m.end():]
    else:
        body = content
    return meta, body


def _is_wrapper_eligible(content: str) -> bool:
    if any(sig in content for sig in TOOL_SIGNALS):
        return False
    # count total occurrences of structural markers (numbered steps or phase/step headings)
    import re as _re
    numbered = len(_re.findall(r"\n\d+\.", content))
    headings = len(_re.findall(r"(?:##\s+(?:Phase|Step)|\*\*(?:Phase|Step))", content))
    return (numbered + headings) >= 2


def _generate_wrapper(skill_name: str, content: str, description: str) -> str:
    """Generate an Ollama-compatible wrapper .md from a plugin SKILL.md."""
    _, body = _parse_frontmatter(content)

    # extract core principle / overview paragraph
    overview_m = re.search(
        r"## (?:Overview|Core Principle|When to Use)\n+(.+?)(?=\n##|\Z)",
        body, re.DOTALL | re.IGNORECASE,
    )
    overview = overview_m.group(1).strip()[:500] if overview_m else description

    # extract phase/step headers for output format
    phases = re.findall(r"^##\s+(?:Phase \d+|Step \d+|[A-Z].+)\n", body, re.MULTILINE)
    phase_list = "\n".join(f"- {p.strip('# \n')}" for p in phases[:8])
    if not phase_list:
        phase_list = "- Analyze the situation\n- Identify root cause\n- Propose solution\n- Verify"

    return f"""---
name: {skill_name}
version: 1
author: claude-plugin-wrapper
model_hint: executor
source: claude-plugin/{skill_name}
---

## System
You are ASHI's {skill_name} specialist. Apply this methodology step by step.
This is a local wrapper of the Claude plugin skill "{skill_name}".
For full capability (tool access, code execution), use this in a Claude Code session.

{overview}

## User Template
Task: {{task}}
Context: {{context}}
Current state: {{current_state}}

Apply the {skill_name} methodology to the task above.
Work through each phase systematically. State findings per phase before proceeding.

## Output Format
{phase_list}

For each phase: what you did → what you found → conclusion before moving on.
"""


def _discover_ollama_skills(skills_path: str) -> dict[str, dict]:
    """Scan skills/ dir for native Ollama skill .md files."""
    skills: dict[str, dict] = {}
    for fname in os.listdir(skills_path):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(skills_path, fname)
        if not os.path.isfile(fpath):
            continue

        with open(fpath, encoding="utf-8") as f:
            content = f.read()

        meta, _ = _parse_frontmatter(content)
        name = meta.get("name", fname[:-3])
        skills[name] = {
            "system": "ollama",
            "path": fpath,
            "model_hint": meta.get("model_hint", "executor"),
            "version": meta.get("version", "1"),
            "author": meta.get("author", "claude"),
            "description": "",
            "invoke": "run_skill",
        }

    # also scan claude-wrappers/
    wrappers_dir = os.path.join(skills_path, "claude-wrappers")
    if os.path.isdir(wrappers_dir):
        for fname in os.listdir(wrappers_dir):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(wrappers_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
            meta, _ = _parse_frontmatter(content)
            base_name = fname[:-3]
            key = f"{base_name}:ollama"
            skills[key] = {
                "system": "ollama",
                "path": fpath,
                "model_hint": meta.get("model_hint", "executor"),
                "version": meta.get("version", "1"),
                "author": "claude-plugin-wrapper",
                "description": f"Ollama wrapper for {base_name} plugin skill",
                "invoke": "run_skill",
                "derived_from": f"claude-plugin/{base_name}",
            }

    return skills


def _best_version_path(plugin_dir: str) -> str:
    """
    Prefer semantic version dirs (1.0.0, 5.0.7) over hash dirs (104d39be).
    Falls back to 'unknown' if nothing else found.
    """
    if not os.path.isdir(plugin_dir):
        return plugin_dir

    entries = [e for e in os.listdir(plugin_dir) if os.path.isdir(os.path.join(plugin_dir, e))]
    semver = [e for e in entries if re.match(r"^\d+\.\d+", e)]
    if semver:
        return os.path.join(plugin_dir, sorted(semver)[-1])
    if "unknown" in entries:
        return os.path.join(plugin_dir, "unknown")
    if entries:
        return os.path.join(plugin_dir, entries[0])
    return plugin_dir


def _discover_plugin_skills(plugin_cache: str) -> dict[str, dict]:
    """Walk plugin cache, find SKILL.md files, return registry entries."""
    skills: dict[str, dict] = {}

    if not os.path.isdir(plugin_cache):
        return skills

    for marketplace in os.listdir(plugin_cache):
        marketplace_path = os.path.join(plugin_cache, marketplace)
        if not os.path.isdir(marketplace_path):
            continue

        for plugin_name in os.listdir(marketplace_path):
            plugin_path = _best_version_path(os.path.join(marketplace_path, plugin_name))
            skills_dir = os.path.join(plugin_path, "skills")
            if not os.path.isdir(skills_dir):
                # some vercel skills use .claude/skills
                skills_dir = os.path.join(plugin_path, ".claude", "skills")
                if not os.path.isdir(skills_dir):
                    continue

            for skill_dir in os.listdir(skills_dir):
                skill_path = os.path.join(skills_dir, skill_dir)
                if not os.path.isdir(skill_path):
                    continue
                # skip upstream dirs (raw content, not skill entrypoints)
                if skill_dir == "upstream":
                    continue

                skill_md = os.path.join(skill_path, "SKILL.md")
                if not os.path.exists(skill_md):
                    continue

                with open(skill_md, encoding="utf-8") as f:
                    content = f.read()

                meta, _ = _parse_frontmatter(content)
                skill_name = meta.get("name", skill_dir)
                description = meta.get("description", "")

                # skip if already indexed from a better version
                if skill_name in skills:
                    continue

                entry: dict = {
                    "system": "claude",
                    "plugin": plugin_name,
                    "marketplace": marketplace,
                    "path": skill_md,
                    "description": description[:200],
                    "invoke": "claude_session",
                }

                # check wrapper eligibility — only set ollama_wrapper path if eligible
                if skill_name in WRAPPER_ELIGIBLE and _is_wrapper_eligible(content):
                    entry["ollama_wrapper"] = os.path.join(WRAPPERS_PATH, f"{skill_name}.md")

                skills[skill_name] = entry

    return skills


def sync(dry_run: bool = False, check_mtime: bool = False) -> dict:
    """
    Main sync function. Returns summary of changes.
    """
    # load existing registry
    existing: dict = {"_meta": {}, "skills": {}}
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH) as f:
            existing = json.load(f)

    if check_mtime:
        generated_at_str = existing.get("_meta", {}).get("generated_at", "")
        if generated_at_str:
            datetime.fromisoformat(generated_at_str)  # validate format
            # check if any SKILL.md is newer than registry
            newest_mtime = 0.0
            for root, dirs, files in os.walk(PLUGIN_CACHE):
                dirs[:] = [d for d in dirs if d != "upstream"]
                for f in files:
                    if f == "SKILL.md":
                        mtime = os.path.getmtime(os.path.join(root, f))
                        newest_mtime = max(newest_mtime, mtime)
            registry_mtime = os.path.getmtime(REGISTRY_PATH)
            if newest_mtime < registry_mtime:
                return {"status": "skipped", "reason": "no changes detected"}

    # discover skills from both systems
    ollama_skills = _discover_ollama_skills(SKILLS_PATH)
    plugin_skills = _discover_plugin_skills(PLUGIN_CACHE)

    # merge: ollama wins on name conflicts
    merged: dict[str, dict] = {}
    merged.update(plugin_skills)
    merged.update(ollama_skills)  # ollama overwrites any plugin skill with same name

    # generate wrappers for eligible plugin skills
    os.makedirs(WRAPPERS_PATH, exist_ok=True)
    wrappers_created = []
    wrappers_skipped = []
    extra_entries: dict[str, dict] = {}

    for name, entry in list(merged.items()):
        # clean up temp fields from all entries
        entry.pop("_wrapper_content", None)
        entry.pop("wrapper_eligible", None)
        entry.pop("_wrapper_desc", None)

    for name, entry in list(merged.items()):
        if entry.get("system") != "claude" or not entry.get("ollama_wrapper"):
            continue

        wrapper_path = entry["ollama_wrapper"]
        # re-read SKILL.md to generate wrapper (content was already cleaned above)
        skill_md_path = entry.get("path", "")
        if not os.path.exists(skill_md_path):
            continue

        with open(skill_md_path, encoding="utf-8") as f:
            skill_content = f.read()

        wrapper_content = _generate_wrapper(name, skill_content, entry.get("description", name))

        if not os.path.exists(wrapper_path):
            if not dry_run:
                with open(wrapper_path, "w", encoding="utf-8") as f:
                    f.write(wrapper_content)
            wrappers_created.append(name)
        else:
            wrappers_skipped.append(name)

        # queue :ollama entry
        ollama_key = f"{name}:ollama"
        if ollama_key not in merged:
            extra_entries[ollama_key] = {
                "system": "ollama",
                "path": wrapper_path,
                "model_hint": "executor",
                "version": "1",
                "author": "claude-plugin-wrapper",
                "description": f"Ollama wrapper for {name} plugin skill",
                "invoke": "run_skill",
                "derived_from": f"claude-plugin/{name}",
            }

    merged.update(extra_entries)

    registry = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ashi_skills_path": SKILLS_PATH,
            "plugin_cache_path": PLUGIN_CACHE,
            "schema_version": 1,
            "ollama_count": sum(1 for e in merged.values() if e.get("system") == "ollama"),
            "claude_count": sum(1 for e in merged.values() if e.get("system") == "claude"),
        },
        "skills": merged,
    }

    if not dry_run:
        with open(REGISTRY_PATH, "w") as f:
            json.dump(registry, f, indent=2)

    return {
        "status": "ok",
        "total_skills": len(merged),
        "ollama_skills": registry["_meta"]["ollama_count"],
        "claude_skills": registry["_meta"]["claude_count"],
        "wrappers_created": wrappers_created,
        "wrappers_skipped": wrappers_skipped,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Claude plugin skills into ASHI registry")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--check-mtime", action="store_true", help="Skip if no SKILL.md files changed")
    args = parser.parse_args()

    result = sync(dry_run=args.dry_run, check_mtime=args.check_mtime)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
