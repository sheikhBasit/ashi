"""
update_entity — upsert an entity page in wiki/entities/ and write to KuzuDB.
Stdlib only. Kuzu wrapped in try/except.
"""
import os
import re
from datetime import datetime

WIKI_PATH = os.path.expanduser("~/Desktop/SecondBrain/wiki")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_existing_facts(content: str) -> list[str]:
    """Extract bullet facts from existing entity page."""
    facts: list[str] = []
    in_facts = False
    for line in content.splitlines():
        if line.strip() == "## Facts":
            in_facts = True
            continue
        if in_facts:
            if line.startswith("##"):
                break
            if line.startswith("- "):
                facts.append(line[2:].strip())
    return facts


def _write_entity_page(
    path: str, name: str, entity_type: str, facts: list[str]
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {name}",
        f"type:: {entity_type}",
        f"updated:: {timestamp}",
        "",
        "## Facts",
    ]
    for fact in facts:
        lines.append(f"- {fact}")
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_to_kuzu(name: str, entity_type: str) -> None:
    try:
        import sys

        venv_site = os.path.expanduser(
            "~/Desktop/SecondBrain/Projects/ashi/.venv/lib/python3.12/site-packages"
        )
        if venv_site not in sys.path:
            sys.path.insert(0, venv_site)

        graph_module_path = os.path.expanduser(
            "~/Desktop/SecondBrain/Projects/ashi/memory"
        )
        if graph_module_path not in sys.path:
            sys.path.insert(0, graph_module_path)

        from kuzu_graph import KnowledgeGraph

        graph = KnowledgeGraph()
        graph.add_node(name, entity_type)
    except Exception:
        pass  # Kuzu optional


def update_entity(
    name: str,
    entity_type: str,
    facts: list[str],
    wiki_path: str = WIKI_PATH,
) -> dict:
    """
    Upsert an entity page in wiki/entities/{slug}.md.
    Merges new facts with existing ones (dedup by exact string).

    Args:
        name:        Entity name (e.g. "ASHI", "Abdul Basit")
        entity_type: Category (e.g. "project", "person", "tool")
        facts:       List of fact strings to add
        wiki_path:   Path to wiki directory

    Returns:
        {"status": "ok", "path": str, "facts_total": int, "facts_added": int}
    """
    wiki_path = os.path.expanduser(wiki_path)
    entities_dir = os.path.join(wiki_path, "entities")
    os.makedirs(entities_dir, exist_ok=True)

    slug = _slug(name)
    page_path = os.path.join(entities_dir, f"{slug}.md")

    existing_facts: list[str] = []
    if os.path.exists(page_path):
        with open(page_path, encoding="utf-8") as f:
            existing_facts = _parse_existing_facts(f.read())

    existing_set = set(existing_facts)
    new_facts = [f for f in facts if f not in existing_set]
    merged = existing_facts + new_facts

    _write_entity_page(page_path, name, entity_type, merged)
    _write_to_kuzu(name, entity_type)

    return {
        "status": "ok",
        "path": page_path,
        "facts_total": len(merged),
        "facts_added": len(new_facts),
    }
