"""
ashi_skill_cli — unified skill management CLI for ASHI.

Commands:
    ashi skill list [--system ollama|claude|all]
    ashi skill info <name>
    ashi skill run <name> [--context key=value ...]
    ashi skill sync [--dry-run] [--check-mtime]

Usage:
    python -m functions.ashi_skill_cli list
    python -m functions.ashi_skill_cli run research --context topic="ASHI architecture" depth=brief
"""
import argparse
import json
import os
import sys

# allow running from project root
sys.path.insert(0, os.path.dirname(__file__))

from skill_registry import get_skill, list_skills


def _col(text: str, code: str) -> str:
    """ANSI color helper."""
    codes = {"green": "32", "yellow": "33", "cyan": "36", "gray": "90", "bold": "1", "reset": "0"}
    return f"\033[{codes.get(code, '0')}m{text}\033[0m"


def cmd_list(system: str = "all") -> None:
    skills = list_skills(system)
    if not skills:
        print("No skills found. Run: ashi skill sync")
        return

    ollama = [s for s in skills if s.get("system") == "ollama"]
    claude = [s for s in skills if s.get("system") == "claude"]

    if system in ("all", "ollama") and ollama:
        print(_col(f"\n  Ollama Skills ({len(ollama)}) — run locally via qwen3:0.6b", "bold"))
        print(_col("  " + "─" * 60, "gray"))
        for s in sorted(ollama, key=lambda x: x["name"]):
            name = s["name"]
            tag = _col("[wrapper]", "gray") if s.get("derived_from") else ""
            desc = s.get("description", "")[:55]
            print(f"  {_col(name, 'green'):<35} {tag} {desc}")

    if system in ("all", "claude") and claude:
        print(_col(f"\n  Claude Plugin Skills ({len(claude)}) — active in Claude Code sessions", "bold"))
        print(_col("  " + "─" * 60, "gray"))
        for s in sorted(claude, key=lambda x: x["name"]):
            name = s["name"]
            plugin = s.get("plugin", "?")
            local = _col(" [+local]", "yellow") if s.get("ollama_wrapper") else ""
            print(f"  {_col(name, 'cyan'):<40} {_col(plugin, 'gray'):<25}{local}")

    print()
    if system == "all":
        print(_col("  Legend: ", "gray") +
              _col("green", "green") + "=ollama  " +
              _col("cyan", "cyan") + "=claude  " +
              _col("[+local]", "yellow") + "=has ollama wrapper  " +
              _col("[wrapper]", "gray") + "=generated from plugin")
    print()


def cmd_info(name: str) -> None:
    entry = get_skill(name)
    if entry is None:
        # try :ollama suffix
        entry = get_skill(f"{name}:ollama")
        if entry:
            name = f"{name}:ollama"
    if entry is None:
        print(f"Skill '{name}' not found. Run: ashi skill list")
        sys.exit(1)

    print(f"\n  {_col(name, 'bold')}")
    print(_col("  " + "─" * 40, "gray"))
    for k, v in entry.items():
        if k.startswith("_"):
            continue
        print(f"  {_col(k, 'gray')}: {v}")
    print()


def cmd_run(name: str, context: dict) -> None:
    entry = get_skill(name)
    if entry is None:
        # try :ollama for convenience
        ollama_entry = get_skill(f"{name}:ollama")
        if ollama_entry:
            print(_col(f"  Routing to local wrapper '{name}:ollama'", "yellow"))
            entry = ollama_entry
            name = f"{name}:ollama"

    if entry is None:
        print(f"Skill '{name}' not found. Run: ashi skill list")
        sys.exit(1)

    system = entry.get("system")

    if system == "ollama":
        from run_skill import run_skill, SkillNotFoundError
        skill_file = entry.get("path", "")
        skills_dir = os.path.dirname(skill_file)
        # get base name from path, strip .md
        skill_base = os.path.splitext(os.path.basename(skill_file))[0]

        print(_col(f"  Running '{skill_base}' via Ollama...", "gray"))
        try:
            result = run_skill(skill_name=skill_base, context=context, skills_path=skills_dir)
            print(_col(f"\n  [{result['model']} | {result['tokens_used']} tokens]\n", "gray"))
            print(result["output"])
            print()
        except SkillNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif system == "claude":
        print(_col("\n  Claude Plugin Skill", "bold"))
        print(_col("  " + "─" * 40, "gray"))
        print(f"  Skill '{name}' is a Claude plugin skill.")
        print(f"  Plugin: {entry.get('plugin', '?')}")
        print(f"  It activates automatically in Claude Code sessions — no manual invocation needed.")
        print(f"  Description: {entry.get('description', '')}")
        if entry.get("ollama_wrapper"):
            print(_col(f"\n  Local alternative available:", "yellow"))
            print(f"  ashi skill run {name}:ollama --context task=\"your task\"")
        print()
    else:
        print(f"Unknown system '{system}' for skill '{name}'")
        sys.exit(1)


def cmd_sync(dry_run: bool = False, check_mtime: bool = False) -> None:
    from sync_plugin_skills import sync
    print(_col("  Syncing plugin skills into ASHI registry...", "gray"))
    result = sync(dry_run=dry_run, check_mtime=check_mtime)
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ashi skill",
        description="ASHI unified skill management",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # list
    p_list = sub.add_parser("list", help="List all skills")
    p_list.add_argument("--system", choices=["ollama", "claude", "all"], default="all")

    # info
    p_info = sub.add_parser("info", help="Show skill details")
    p_info.add_argument("name")

    # run
    p_run = sub.add_parser("run", help="Run a skill")
    p_run.add_argument("name")
    p_run.add_argument(
        "--context", nargs="*", default=[],
        metavar="KEY=VALUE",
        help="Template variables, e.g. --context topic=ASHI depth=brief",
    )

    # sync
    p_sync = sub.add_parser("sync", help="Sync plugin skills into registry")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.add_argument("--check-mtime", action="store_true")

    args = parser.parse_args()

    if args.cmd == "list":
        cmd_list(args.system)
    elif args.cmd == "info":
        cmd_info(args.name)
    elif args.cmd == "run":
        ctx = {}
        for pair in (args.context or []):
            if "=" in pair:
                k, v = pair.split("=", 1)
                ctx[k.strip()] = v.strip()
        cmd_run(args.name, ctx)
    elif args.cmd == "sync":
        cmd_sync(dry_run=args.dry_run, check_mtime=args.check_mtime)


if __name__ == "__main__":
    main()
