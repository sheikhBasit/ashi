# ASHI Phase 1 — Function Tools, Skill Library, Tool Calling
**Date:** 2026-04-08
**Depends on:** Phase 0 complete (14/14 tests passing, Langfuse OK, 3 models available)
**Goal:** ASHI can receive a task, pick a skill, call functions, and produce a wiki-logged result — entirely locally.

---

## Deliverables

| # | Deliverable | Done? |
|---|-------------|-------|
| 1.0 | Install remaining deps (sentence-transformers, llmlingua) | [ ] |
| 1.1 | `functions/ingest_source.py` | [ ] |
| 1.2 | `functions/update_entity.py` | [ ] |
| 1.3 | `functions/review_task.py` (judge agent) | [ ] |
| 1.4 | `functions/run_skill.py` | [ ] |
| 1.5 | `functions/tool_dispatch.py` (JSON router) | [ ] |
| 1.6 | Skill library — 7 seed skills | [ ] |
| 1.7 | MCP server config (Filesystem, Obsidian, GitHub, Brave) | [ ] |
| 1.8 | deepseek-r1 tool-calling Modelfile fix | [ ] |
| 1.9 | qwen3:4b tool-calling verification | [ ] |
| 1.10 | Integration test: full TCU round-trip | [ ] |
| 1.11 | Phase 1 tests (12 new tests) | [ ] |

---

## Task 1.0 — Install Remaining Dependencies

Torch 2.10.0 CPU is installed. Now install the rest:

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
source .venv/bin/activate
pip install sentence-transformers llmlingua2 --quiet
```

**Verify:**
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
print(model.encode(["hello"]).shape)  # (1, 384)
```

LLMLingua-2 is used in `compress_prompt()` in Phase 2 — just install now, wire up later.

---

## Task 1.1 — `functions/ingest_source.py`

**Contract:**
```python
ingest_source(source: str, label: str = "", wiki_path: str = WIKI_PATH) -> dict
# source: URL, file path, or raw text
# Returns: {"status": "ok", "chunks": int, "wiki_file": str}
```

**Implementation plan:**
1. Detect source type: URL → fetch with `urllib`, file → read, str → use directly
2. Chunk at 800-token boundaries (split on `\n\n` then merge until ~800 words)
3. Write one wiki page per chunk: `wiki/ingest/YYYY-MM-DD-{slug}.md`
4. Call `append_wiki_log()` with event_type="ingest"
5. Call `vector_store.add()` for each chunk (LanceDB)
6. Return chunk count and wiki file path

**No external deps** — urllib, os, re only. LanceDB import wrapped in try/except.

---

## Task 1.2 — `functions/update_entity.py`

**Contract:**
```python
update_entity(name: str, entity_type: str, facts: list[str], wiki_path: str = WIKI_PATH) -> dict
# Upserts an entity page in wiki/entities/{name}.md
# Also writes to KuzuDB as a node
# Returns: {"status": "ok", "path": str, "facts_added": int}
```

**Entity page format:**
```markdown
# {name}
type:: {entity_type}
updated:: YYYY-MM-DD HH:MM

## Facts
- {fact1}
- {fact2}
```

**Implementation plan:**
1. Sanitize name → slug (lowercase, hyphens)
2. Read existing page if present, extract existing facts
3. Merge new facts (dedup by exact string match)
4. Overwrite page with merged facts + updated timestamp
5. Call `knowledge_graph.add_node(name, entity_type)` — wrapped in try/except
6. Return status

---

## Task 1.3 — `functions/review_task.py` (Judge Agent)

**Contract:**
```python
review_task(tcu_id: str, tasks_path: str = TASKS_PATH) -> dict
# Loads completed TCU, calls local judge model, returns scored result
# Returns: {"score": 0-10, "verdict": "pass"|"fail"|"retry", "notes": str}
```

**Judge prompt template** (injected into qwen3:4b):
```
You are a strict quality judge for an AI assistant.
Review this completed task and output ONLY valid JSON:
{"score": <0-10>, "verdict": "<pass|fail|retry>", "notes": "<one sentence>"}

Task intent: {intent}
Steps completed: {steps}
Final output: {output}
```

**Scoring rules:**
- 8-10 → pass
- 5-7 → retry (re-run with different skill)
- 0-4 → fail (escalate to Claude)

**Model call:** Ollama HTTP API (`executor` model = qwen3:4b-16k). No OpenAI SDK — raw `urllib.request.urlopen`.

**Score stored in TCU JSON** under `judge` key. Appended to `~/Desktop/SecondBrain/AI/agent-logs/YYYY-MM-DD.log`.

---

## Task 1.4 — `functions/run_skill.py`

**Contract:**
```python
run_skill(skill_name: str, context: dict, model: str = "executor") -> dict
# Loads skill from skills/{skill_name}.md
# Injects context into skill prompt
# Calls local model via Ollama
# Returns: {"output": str, "model": str, "tokens_used": int}
```

**Implementation plan:**
1. Load `skills/{skill_name}.md` — raise `SkillNotFoundError` if missing
2. Parse skill file: extract `## System`, `## User Template`, `## Output Format` sections
3. Render user template: `template.format(**context)` (safe, no eval)
4. Call Ollama `/api/chat` with system + rendered user message
5. Parse response, extract token counts from Ollama metadata
6. Append to `AI/agent-logs/YYYY-MM-DD.log`
7. Return output + metadata

**Skill file format** (canonical):
```markdown
---
name: {skill_name}
version: 1
author: claude
model_hint: executor
---

## System
{system_prompt}

## User Template
{user_template_with_{placeholders}}

## Output Format
{expected_output_format}
```

---

## Task 1.5 — `functions/tool_dispatch.py` (JSON Router)

This is the core of local tool calling. Models output JSON, this module executes it.

**Tool registry:**
```python
TOOL_REGISTRY = {
    "search_wiki": search_wiki,
    "ingest_source": ingest_source,
    "update_entity": update_entity,
    "create_tcu": create_tcu,
    "review_task": review_task,
    "run_skill": run_skill,
    "append_wiki_log": append_wiki_log,
    "lint_wiki": lint_wiki,
    "emit_metric": emit_metric,
}
```

**Contract:**
```python
dispatch(tool_call: dict) -> dict
# tool_call: {"tool": "search_wiki", "args": {"query": "...", "wiki_path": "..."}}
# Returns: tool result dict or {"error": str}
```

**Tool call format** (models must output this JSON exactly):
```json
{"tool": "<tool_name>", "args": {<kwargs>}}
```

**Implementation plan:**
1. Validate `tool_call` has `tool` and `args` keys
2. Look up in `TOOL_REGISTRY` — return error if not found
3. Call `fn(**args)` in try/except
4. Return result or `{"error": str(e), "tool": tool_name}`
5. Emit metric: `ashi_tool_dispatch_total` with `tool` label

**Extraction helper:**
```python
extract_tool_calls(llm_response: str) -> list[dict]
# Finds all ```json ... ``` blocks in LLM response
# Parses each, filters for those with "tool" key
# Returns list of valid tool calls
```

Models that don't support native tool calling (deepseek-r1) output tool calls inline in code blocks. This function extracts them.

---

## Task 1.6 — Seed Skill Library

Create `~/Desktop/SecondBrain/Projects/ashi/skills/` directory with 7 skills.

### Skill: `research.md`
- **Purpose:** Search wiki + web, synthesize findings, output structured summary
- **Tools used:** `search_wiki`, optionally Brave Search
- **Template placeholders:** `{topic}`, `{depth}` (brief/detailed)

### Skill: `plan.md`
- **Purpose:** Break a goal into ordered TCU steps, output JSON plan
- **Tools used:** `create_tcu`
- **Template placeholders:** `{goal}`, `{context}`, `{constraints}`

### Skill: `code.md`
- **Purpose:** Write code for a spec, output file path + code block
- **Tools used:** none (output only)
- **Template placeholders:** `{spec}`, `{language}`, `{existing_code}`

### Skill: `review.md`
- **Purpose:** Review code or text for quality, output scored feedback
- **Tools used:** none
- **Template placeholders:** `{artifact}`, `{criteria}`

### Skill: `ingest.md`
- **Purpose:** Process a source, extract key facts, update wiki
- **Tools used:** `ingest_source`, `update_entity`, `append_wiki_log`
- **Template placeholders:** `{source}`, `{label}`

### Skill: `daily-report.md`
- **Purpose:** Summarize today's work from intent log + TCU completions
- **Tools used:** `search_wiki`, `lint_wiki`
- **Template placeholders:** `{date}`, `{projects}`

### Skill: `wiki-update.md`
- **Purpose:** Refresh a wiki entity with new facts from a source
- **Tools used:** `search_wiki`, `update_entity`
- **Template placeholders:** `{entity_name}`, `{new_facts}`

---

## Task 1.7 — MCP Server Configuration

### 1.7.1 Filesystem MCP (already available in Claude Code)
- No install needed. Used for reading/writing Second Brain files.
- Restrict to `~/Desktop/SecondBrain/` only.

### 1.7.2 Obsidian MCP
**Install:** `npm install -g @cyanheads/obsidian-mcp-server`
**Config** (`~/.claude/mcp-full.json` servers block):
```json
{
  "obsidian": {
    "command": "npx",
    "args": ["@cyanheads/obsidian-mcp-server"],
    "env": {
      "OBSIDIAN_VAULT_PATH": "/home/basitdev/Desktop/SecondBrain",
      "OBSIDIAN_API_KEY": ""
    }
  }
}
```
**Purpose:** Open specific notes, create pages, trigger graph view — enables Claude to author wiki pages directly via tool calls.

### 1.7.3 GitHub MCP
**Install:** `npm install -g @modelcontextprotocol/server-github`
**Config:**
```json
{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
  }
}
```
**Purpose:** Create issues, PRs, read repo files — ASHI can autonomously manage code repos.

### 1.7.4 Brave Search MCP
**Install:** `npm install -g @modelcontextprotocol/server-brave-search`
**Config:**
```json
{
  "brave-search": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-brave-search"],
    "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"}
  }
}
```
**Note:** Brave API key required (free tier: 2000 queries/month). Store in `~/.ashi/secrets.db` via `SecretsVault`.

**Alternative if no API key:** Use Playwright MCP (`@playwright/mcp`) for headless web search. Already available.

---

## Task 1.8 — deepseek-r1 Tool Calling Modelfile

deepseek-r1 doesn't natively support Ollama's tool-calling API. Fix via custom Modelfile that injects tool schemas into the system prompt:

```bash
# Pull MFDoom fork (already at localhost:11434 as deepseek-r1:8b-0528-...)
# No new model needed — use system prompt injection instead

cat > /tmp/ashi-planner.modelfile << 'EOF'
FROM deepseek-r1:8b-0528-qwen3-q4_K_M-16k

SYSTEM """
You are ASHI's planning brain. When you need to call a tool, output ONLY this JSON in a code block:
```json
{"tool": "<tool_name>", "args": {<arguments>}}
```

Available tools:
- search_wiki(query, wiki_path, top_k) → search knowledge base
- create_tcu(intent, steps, priority) → create a task unit
- run_skill(skill_name, context) → execute a skill
- ingest_source(source, label) → ingest content into wiki
- update_entity(name, entity_type, facts) → update wiki entity

Think step by step inside <think>...</think> tags. Then output your tool call or final answer.
"""

PARAMETER num_ctx 16384
PARAMETER temperature 0.1
EOF

ollama create ashi-planner -f /tmp/ashi-planner.modelfile
```

Update `~/.ashi/config.json` planner model to `ashi-planner`.

---

## Task 1.9 — qwen3:4b Tool Calling Verification

qwen3:4b supports native Ollama tool calling via the `/api/chat` `tools` parameter.

**Verification script:**
```python
import json, urllib.request

payload = {
    "model": "qwen3:4b-16k",
    "messages": [{"role": "user", "content": "Search the wiki for ASHI"}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "search_wiki",
            "description": "Search the wiki",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }],
    "stream": False
}

req = urllib.request.Request(
    "http://localhost:11434/api/chat",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}
)
resp = json.loads(urllib.request.urlopen(req).read())
print(resp["message"])
```

Expected: `message.tool_calls` list with `search_wiki` call. If native tool calling works, `run_skill.py` can use it for executor model calls. If not, falls back to `extract_tool_calls()` from `tool_dispatch.py`.

---

## Task 1.10 — Integration Test: Full TCU Round-Trip

**Test scenario:** "Summarize what ASHI is and save to wiki"

1. `extract_intent("Summarize what ASHI is and save to wiki")` → `{"action": "wiki", "entity": "ASHI"}`
2. `create_tcu(intent, steps=["search_wiki", "run_skill:ingest", "update_entity"])` → TCU JSON
3. `run_skill("research", {"topic": "ASHI", "depth": "brief"})` → markdown summary
4. `update_entity("ASHI", "project", [summary])` → wiki page updated
5. `review_task(tcu_id)` → `{"score": 8, "verdict": "pass"}`
6. TCU marked done, intent logged, metric emitted

**Script:** `~/Desktop/SecondBrain/Projects/ashi/tests/test_integration_phase1.py`

---

## Task 1.11 — Phase 1 Tests

12 new tests in `tests/`:

| Test file | Tests |
|-----------|-------|
| `test_ingest.py` | ingest URL (mocked urllib), ingest text, ingest file |
| `test_update_entity.py` | create entity, update existing, dedup facts |
| `test_review_task.py` | pass verdict, fail verdict, retry verdict (mocked Ollama) |
| `test_run_skill.py` | load skill, render template, skill not found error |
| `test_tool_dispatch.py` | valid dispatch, unknown tool, extract_tool_calls from LLM response |

**Run all (Phase 0 + Phase 1):**
```bash
cd ~/Desktop/SecondBrain/Projects/ashi
source .venv/bin/activate
python -m pytest tests/ -v --tb=short
# Target: 26/26 passing
```

---

## Execution Order

```
1.0 deps          → parallel with 1.8 Modelfile
1.1 ingest_source
1.2 update_entity → depends on wiki.py (done)
1.3 review_task   → needs Ollama running
1.4 run_skill     → needs skills/ dir
1.5 tool_dispatch → depends on 1.1–1.4
1.6 skill library → parallel with 1.5
1.7 MCP config    → parallel with 1.5–1.6
1.8 Modelfile     → parallel with 1.0
1.9 qwen3 verify  → after 1.5
1.10 integration  → after all above
1.11 tests        → parallel with 1.10
```

---

## Phase 1 Acceptance Criteria

- [ ] `python -m pytest tests/ -v` → 26/26 passing
- [ ] `ashi search "ASHI project"` returns wiki results
- [ ] `ashi task "summarize ASHI"` completes full TCU cycle without Claude
- [ ] Judge scores are written to agent-logs
- [ ] At least 5 skills loadable via `run_skill()`
- [ ] `ashi status` shows all 3 models + Langfuse OK + tool dispatch registered

---

## Phase 2 Preview (after Phase 1 complete)

- Bubblewrap sandbox for skill execution
- LLMLingua-2 prompt compression (< 500 token budget)
- Ralph Loop: daily skill scoring + Claude improvement cycle
- Mem0 episodic memory integration
- Tauri desktop app shell (React + React Flow node graph)
