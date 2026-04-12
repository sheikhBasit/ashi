# functions/action_classifier.py
"""
Action classifier — determines if a tool call is safe to execute without confirmation.

REVERSIBLE: read-only, no external side effects, undoable
IRREVERSIBLE: writes data, deletes files, sends network requests, modifies system state

Unknown tools default to IRREVERSIBLE (safe default).
"""
from enum import Enum
import re


class ActionRisk(str, Enum):
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


# Tools that are always safe (read-only)
_REVERSIBLE_TOOLS = {
    "search_wiki",
    "lint_wiki",
    "run_skill",
    "list_skills",
    "get_skill_info",
    "ide_list_extensions",
    "ide_status",
    # Computer control — read-only tools
    "screen_capture",      # takes a screenshot, no side effects
    "screen_read",         # OCR on screenshot, read-only
    "find_on_screen",      # OCR search, read-only
    "screen_understand",   # vision model analysis, read-only
    "cc_health",           # health check, read-only
}

# Tools that are always irreversible (write/delete/network)
_IRREVERSIBLE_TOOLS = {
    "ingest_source",
    "update_entity",
    "review_task",
    "create_tcu",
    "append_wiki_log",
    "ide_route",
    "ide_open",
    "ide_switch_model",
    "ide_toggle_copilot",
    "ide_install_extension",
    "ide_smart_open",
    "opencode",
    "emit_metric",
    # Computer control — tools that affect system state
    "mouse_move",          # moves cursor — visible but low risk
    "mouse_click",         # clicks — can trigger actions
    "mouse_scroll",        # scrolls — low risk but changes view state
    "keyboard_type",       # types text — can modify documents
    "keyboard_key",        # presses keys — can trigger shortcuts
    "open_app",            # launches applications
    "focus_window",        # changes focused window
}

# Shell commands that are read-only (prefix/exact match)
_SAFE_SHELL_PREFIXES = (
    "ls ",
    "ls\n",
    "ls",
    "cat ",
    "head ",
    "tail ",
    "grep ",
    "find ",
    "du ",
    "df ",
    "ps ",
    "top ",
    "htop",
    "pwd",
    "echo ",
    "which ",
    "type ",
    "env",
    "printenv",
    "git log",
    "git status",
    "git diff",
    "git show",
    "python ",
    "python3 ",
)

# Shell patterns that are always irreversible
_DANGEROUS_SHELL_PATTERNS = re.compile(
    r"\brm\b|\bmv\b|\bcp\b|\bchmod\b|\bchown\b|"
    r"\bsudo\b|\bapt\b|\bpip\b|\bnpm\b|\byarn\b|"
    r"\bcurl\b|\bwget\b|\bssh\b|\bscp\b|\brsync\b|"
    r">\s*[^\s]|>>\s*[^\s]|\|\s*tee\b"
)


def classify_action(tool_name: str, args: dict) -> ActionRisk:
    """
    Classify a tool call as REVERSIBLE or IRREVERSIBLE.

    Args:
        tool_name: Name of the tool to call
        args: Arguments dict for the tool call

    Returns:
        ActionRisk.REVERSIBLE or ActionRisk.IRREVERSIBLE
    """
    if tool_name in _REVERSIBLE_TOOLS:
        return ActionRisk.REVERSIBLE

    if tool_name in _IRREVERSIBLE_TOOLS:
        return ActionRisk.IRREVERSIBLE

    if tool_name == "run_shell":
        command = args.get("command", "").strip()
        if _DANGEROUS_SHELL_PATTERNS.search(command):
            return ActionRisk.IRREVERSIBLE
        if any(command.startswith(p) for p in _SAFE_SHELL_PREFIXES):
            return ActionRisk.REVERSIBLE
        return ActionRisk.IRREVERSIBLE

    # unknown tool — default safe
    return ActionRisk.IRREVERSIBLE
