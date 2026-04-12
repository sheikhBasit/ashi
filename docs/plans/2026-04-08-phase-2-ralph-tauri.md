# Phase 2: Ralph Loop + Tauri Desktop App
**Date:** 2026-04-08
**Project:** ~/Desktop/SecondBrain/Projects/ashi
**Estimated Duration:** 4 weeks (Week 5-8)

## Summary

Phase 2 has two independent streams. Stream A builds the Ralph Loop — a nightly
cron job that reviews yesterday's work, scores skills, rewrites weak ones via
Claude, tests the new versions, and promotes winners. Stream B builds the Tauri v2
desktop app with chat, wiki viewer, and pipeline builder panels.

Both streams share no code dependencies. Build Stream A first (1 week), then
Stream B (3 weeks). Stream A validates before desktop work begins.

---

## Stream A: Ralph Loop

### Architecture

```
cron (3am) → functions/ralph.py
  ├── read intent-log.md (last 24h)
  ├── load TCUs from tasks/done/ matching those intents
  ├── skill_scorer.py: aggregate scores per skill
  ├── identify weak skills (avg < 6 OR fail rate > 30%)
  ├── call Claude API to rewrite weak skill markdown
  ├── test new version against 3 recent tasks (mocked Ollama)
  ├── promote if better → skills/{name}.md, retire old → skills/archive/
  ├── append learnings to wiki/log.md
  └── write ralph-YYYY-MM-DD.log
```

### Files to Create

| File | Purpose |
|------|---------|
| `functions/skill_scorer.py` | Score skills from TCU judge history |
| `functions/ralph.py` | Ralph Loop engine (daily cron entry point) |
| `tests/test_skill_scorer.py` | 3 tests for scoring logic |
| `tests/test_ralph.py` | 4 tests for full loop (all external calls mocked) |
| `skills/archive/` | Directory for retired skill versions |

### Files That Change

| File | What Changes |
|------|-------------|
| `~/.ashi/config.json` | Add `claude_api_key_env` field and `ralph.schedule` field |
| User crontab | Add `0 3 * * * cd ~/Desktop/SecondBrain/Projects/ashi && .venv/bin/python -m functions.ralph` |

### Files That Stay The Same

- All existing `functions/*.py` (ingest, wiki, tcu, review_task, run_skill, tool_dispatch)
- All existing `skills/*.md`
- All existing `tests/test_*.py`

---

### Task A1: skill_scorer.py — Score Skills from TCU History

**File:** `functions/skill_scorer.py`

**Inputs:**
- `tasks_path: str` — path to `tasks/` directory
- `hours: int = 24` — lookback window

**Logic:**
1. Scan `tasks/done/*.json` for TCUs completed within the last `hours` hours
2. For each TCU, read `judge.score` and `judge.verdict` fields (written by `review_task`)
3. Group by skill name (read from TCU steps — each step that called `run_skill` logs the skill name)
4. Per skill, compute: `task_count`, `avg_score`, `fail_rate` (verdict == "fail"), `pass_rate`
5. Return `list[dict]` sorted by avg_score ascending

**Function signature:**
```python
def score_skills(tasks_path: str, hours: int = 24) -> list[dict]:
    """
    Returns: [{"skill": str, "task_count": int, "avg_score": float,
               "fail_rate": float, "pass_rate": float, "tcu_ids": list[str]}]
    """
```

**Helper:**
```python
def identify_weak_skills(scores: list[dict], min_avg: float = 6.0, max_fail: float = 0.3) -> list[dict]:
    """Filter to skills with avg_score < min_avg OR fail_rate > max_fail."""
```

**Acceptance criteria:**
- Correctly parses TCU JSON files matching the schema in `tcu.py` (fields: `judge.score`, `judge.verdict`, `steps.*.output` containing skill name)
- Handles empty `tasks/done/` gracefully (returns empty list)
- Handles TCUs with no `judge` field (skips them)
- Time filtering uses `completed_at` ISO timestamp from TCU

---

### Task A2: ralph.py — Ralph Loop Engine

**File:** `functions/ralph.py`

**Dependencies:** Task A1 must be complete.

**Imports from existing code:**
- `skill_scorer.score_skills`, `skill_scorer.identify_weak_skills`
- `intent.parse_intent_log`
- `wiki.append_wiki_log`
- `run_skill._load_skill` (to read current skill markdown)

**Function: `run_ralph_loop()`**

Step-by-step logic:

```python
def run_ralph_loop(
    config_path: str = "~/.ashi/config.json",
    dry_run: bool = False,
) -> dict:
```

1. **Load config** from `~/.ashi/config.json`
2. **Read intent log** — call `parse_intent_log()`, filter to last 24h entries
3. **Score skills** — call `score_skills(tasks_path, hours=24)`
4. **Identify weak** — call `identify_weak_skills(scores)`
5. **For each weak skill:**
   a. Load current skill markdown via `_load_skill()`
   b. Call Claude API (httpx POST to `https://api.anthropic.com/v1/messages`) with prompt:
      ```
      You are rewriting an ASHI skill file. The skill "{name}" scored {avg_score}/10
      with {fail_rate}% failure rate over {task_count} tasks.
      Current skill: {skill_markdown}
      Recent failure examples: {failure_outputs}
      Write an improved version. Keep the same frontmatter format. Output ONLY the
      full skill markdown, nothing else.
      ```
   c. Save new version to `skills/{name}.md.new`
   d. **Test new version:** replay 3 recent failed TCUs through `run_skill()` with
      Ollama mocked to return the same input (deterministic test). Compare judge
      scores of new output vs old output.
   e. If new version scores better on >= 2 of 3 tests:
      - Move old to `skills/archive/{name}_v{N}_{date}.md`
      - Move `.new` to `skills/{name}.md`
      - Log promotion
   f. If not better: delete `.new`, log "kept current version"
6. **Update wiki** — append learnings entry to `wiki/log.md` via `append_wiki_log()`
7. **Write log** — full run summary to `AI/agent-logs/ralph-YYYY-MM-DD.log`
8. Return summary dict: `{"skills_scored": N, "weak_found": N, "promoted": [...], "kept": [...]}`

**Claude API call details:**
- Use `ANTHROPIC_API_KEY` from env (never hardcode)
- Model: config `models.fallback` (claude-sonnet-4-6)
- Max tokens: 2000
- Use stdlib `urllib.request` to match existing codebase pattern (no httpx for this)
- If API fails, log error and skip that skill (never crash the loop)

**Cron entry point (`__main__` block):**
```python
if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    result = run_ralph_loop(dry_run=dry)
    print(json.dumps(result, indent=2))
```

**Acceptance criteria:**
- Full loop runs without error when there are zero weak skills (no-op path)
- Claude API failure does not crash the loop (logged, skipped)
- Old skills are archived with timestamp in filename before overwrite
- `dry_run=True` mode prints what it would do without writing any files
- Log file written to correct path with timestamp per line
- The module is runnable via `python -m functions.ralph`

---

### Task A3: Tests for Stream A

**File:** `tests/test_skill_scorer.py` (3 tests)

1. `test_score_skills_with_judged_tcus` — Create 3 TCU JSON files in a tmp dir with
   `judge` fields and varying scores. Verify `score_skills()` returns correct
   avg_score and fail_rate per skill.

2. `test_score_skills_empty_dir` — Empty `done/` dir returns empty list.

3. `test_identify_weak_skills` — Given a list of score dicts, verify filtering
   at threshold boundaries (score exactly 6.0 = not weak, 5.9 = weak).

**File:** `tests/test_ralph.py` (4 tests)

All tests mock: `_call_claude()`, `run_skill._call_ollama()`, filesystem reads.

1. `test_ralph_no_weak_skills` — All skills score > 6, fail_rate < 30%.
   Verify loop returns `{"promoted": [], "kept": []}`.

2. `test_ralph_promotes_better_skill` — One weak skill. Mocked Claude returns
   improved version. Mocked test shows new version scores higher. Verify old
   skill moved to `archive/`, new skill in place.

3. `test_ralph_keeps_when_new_is_worse` — Mocked Claude returns a version that
   scores worse. Verify `.new` file deleted, original untouched.

4. `test_ralph_claude_api_failure` — Mock Claude API to raise exception.
   Verify loop completes without error, logs the failure.

**Test pattern:** Match existing test style — use `tempfile.TemporaryDirectory`,
`unittest.mock.patch`, direct function imports via `sys.path.insert`.

**Acceptance criteria:**
- All 7 new tests pass with `pytest tests/test_skill_scorer.py tests/test_ralph.py -v`
- No tests require network access (all external calls mocked)
- Tests run in under 5 seconds total

---

### Task A4: Cron Setup + Validation

**After A1-A3 pass:**

1. Create `skills/archive/` directory (empty, with `.gitkeep`)
2. Add crontab entry:
   ```
   0 3 * * * cd ~/Desktop/SecondBrain/Projects/ashi && .venv/bin/python -m functions.ralph >> ~/Desktop/SecondBrain/AI/agent-logs/ralph-$(date +\%Y-\%m-\%d).log 2>&1
   ```
3. Manual validation: run `python -m functions.ralph --dry-run` and verify output

**Acceptance criteria:**
- `crontab -l` shows the ralph entry
- `python -m functions.ralph --dry-run` exits 0 and prints valid JSON summary
- `skills/archive/` directory exists

---

## Stream B: Tauri Desktop App

### Prerequisites Check

Before starting Stream B, verify these are installed:
```bash
rustc --version    # need >= 1.77
cargo --version
node --version     # need >= 18
npm --version
# Tauri v2 system deps (Ubuntu):
sudo apt install libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf
```

### Directory Structure

```
app/
├── src-tauri/
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── src/
│   │   ├── main.rs          ← Tauri entry + IPC command registrations
│   │   ├── commands/
│   │   │   ├── mod.rs
│   │   │   ├── skill.rs     ← run_skill, list_skills
│   │   │   ├── tool.rs      ← dispatch_tool
│   │   │   ├── wiki.rs      ← read_wiki (BM25 search)
│   │   │   ├── tcu.rs       ← get_tcu_list
│   │   │   └── pipeline.rs  ← run_pipeline
│   │   └── python_bridge.rs ← subprocess runner for Python functions
│   └── icons/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── MainCanvas.tsx
│   │   │   └── RightPanel.tsx
│   │   ├── pipeline/
│   │   │   ├── PipelineBuilder.tsx
│   │   │   ├── nodes/
│   │   │   │   ├── InputNode.tsx
│   │   │   │   ├── AgentNode.tsx
│   │   │   │   ├── FunctionNode.tsx
│   │   │   │   ├── ConditionNode.tsx
│   │   │   │   └── OutputNode.tsx
│   │   │   └── PipelineToolbar.tsx
│   │   ├── chat/
│   │   │   ├── ChatPanel.tsx
│   │   │   └── MessageBubble.tsx
│   │   ├── wiki/
│   │   │   ├── WikiViewer.tsx
│   │   │   └── WikiSearch.tsx
│   │   ├── tasks/
│   │   │   └── TaskMonitor.tsx
│   │   ├── skills/
│   │   │   └── SkillsList.tsx
│   │   └── logs/
│   │       └── LogViewer.tsx
│   ├── hooks/
│   │   ├── useIpc.ts         ← typed Tauri invoke wrappers
│   │   └── usePipeline.ts    ← React Flow state management
│   ├── types/
│   │   └── index.ts          ← shared TypeScript interfaces
│   └── lib/
│       └── ipc.ts            ← Tauri command bindings
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
└── vite.config.ts
```

### Implementation Order

Stream B is broken into 4 sub-phases. Each must be working before the next starts.

---

### Task B1: Tauri + React Scaffold (Day 1-2)

**What to do:**
1. `cd ~/Desktop/SecondBrain/Projects/ashi && npm create tauri-app@latest app -- --template react-ts`
2. Inside `app/`: install deps:
   ```bash
   npm install @tauri-apps/api @tauri-apps/plugin-shell
   npm install -D tailwindcss @tailwindcss/vite
   npm install react-flow-renderer @xyflow/react
   npm install react-markdown remark-gfm
   npm install lucide-react
   ```
3. Set up Tailwind (v4 CSS import style, no config file needed)
4. Set up shadcn/ui: `npx shadcn@latest init` then add: button, input, scroll-area, tabs, separator, dialog, dropdown-menu, card
5. Create the 3-panel layout shell in `App.tsx`:
   - Left: `Sidebar.tsx` (240px fixed width, nav items: Projects, Tasks, Wiki, Skills, Logs)
   - Center: `MainCanvas.tsx` (flex-1, renders active view based on sidebar selection)
   - Right: `RightPanel.tsx` (320px fixed width, chat panel)
6. Wire Tauri window config in `tauri.conf.json`: title "ASHI", width 1440, height 900, resizable true
7. Verify: `cd app && npm run tauri dev` opens a window with the 3-panel layout

**Acceptance criteria:**
- `npm run tauri dev` launches without errors
- Three-panel layout visible with sidebar navigation
- Clicking sidebar items changes the center panel view (even if views are placeholder text)
- Tailwind classes render correctly
- shadcn/ui Button component renders in the sidebar

---

### Task B2: Rust IPC Commands + Python Bridge (Day 3-5)

**What to do:**

Create `src-tauri/src/python_bridge.rs`:
```rust
// Runs Python functions as subprocesses
// Command: .venv/bin/python -c "from functions.{module} import {func}; ..."
// Returns stdout as String, stderr as error
pub fn call_python(function_path: &str, args_json: &str) -> Result<String, String>
```

The bridge calls Python via `std::process::Command`, passing JSON args as a CLI
argument, and reading JSON output from stdout. This avoids embedding Python or
needing FFI.

**Python CLI wrapper** (new file): `functions/cli_bridge.py`
```python
"""CLI entry point for Tauri IPC. Usage: python -m functions.cli_bridge <function> <json_args>"""
# Dispatches to tool_dispatch.dispatch() and prints JSON result to stdout
```

**Tauri IPC commands** (in `src-tauri/src/commands/`):

| Command | Rust function | What it does |
|---------|--------------|-------------|
| `run_skill` | `commands::skill::run_skill(name: String, context: String)` | Calls Python `run_skill` via bridge |
| `list_skills` | `commands::skill::list_skills()` | Reads `skills/` dir, returns `Vec<SkillInfo>` |
| `dispatch_tool` | `commands::tool::dispatch_tool(tool: String, args: String)` | Calls Python `tool_dispatch` via bridge |
| `read_wiki` | `commands::wiki::read_wiki(query: String)` | Calls Python `search_wiki` via bridge |
| `get_tcu_list` | `commands::tcu::get_tcu_list()` | Reads `tasks/active/*.json`, returns list |
| `run_pipeline` | `commands::pipeline::run_pipeline(nodes: String, edges: String)` | Executes node graph sequentially |

Register all commands in `main.rs` via `tauri::Builder::default().invoke_handler(...)`.

**Frontend typed bindings** (`src/lib/ipc.ts`):
```typescript
import { invoke } from '@tauri-apps/api/core';

export async function runSkill(name: string, context: Record<string, string>): Promise<SkillResult> {
  return invoke('run_skill', { name, context: JSON.stringify(context) });
}
// ... one function per IPC command
```

**Acceptance criteria:**
- `list_skills` IPC command returns the 7 skill names from `skills/` dir
- `read_wiki` IPC command with query "ASHI" returns search results
- `dispatch_tool` with `{"tool": "lint_wiki", "args": {"wiki_path": "~/Desktop/SecondBrain/wiki"}}` returns valid JSON
- Python subprocess errors are caught and returned as `{ error: string }` to frontend
- All commands are callable from browser devtools via `window.__TAURI__.invoke()`

---

### Task B3: Core Panels — Wiki + Tasks + Skills + Logs (Day 6-10)

**Build these panels in order (each one is usable standalone):**

**B3.1 Wiki Viewer** (`components/wiki/WikiViewer.tsx`):
- Text input for search query, calls `read_wiki` IPC
- Displays search results as clickable list
- Clicking a result loads the full markdown file (new IPC: `read_file(path)`)
- Renders markdown with `react-markdown` + `remark-gfm`
- `[[wikilinks]]` rendered as clickable internal links
- "Open in Obsidian" button: `window.open('obsidian://open?path=' + encodeURIComponent(path))`

**B3.2 Task Monitor** (`components/tasks/TaskMonitor.tsx`):
- Calls `get_tcu_list` on mount
- Table/list view: ID, intent (truncated), status badge (pending/running/done/failed), judge score
- Click a task to see full TCU JSON in a slide-over panel
- Auto-refresh every 30 seconds

**B3.3 Skills List** (`components/skills/SkillsList.tsx`):
- Calls `list_skills` on mount
- Card grid: skill name, version, model_hint, author
- Click to view full skill markdown (rendered)
- "Run Skill" button opens a dialog with context input fields

**B3.4 Log Viewer** (`components/logs/LogViewer.tsx`):
- Reads `AI/agent-logs/` directory via IPC
- Lists log files by date (most recent first)
- Click to view log file contents in a monospace scroll area
- Auto-scroll to bottom, search/filter by text

**Acceptance criteria per panel:**
- Wiki: search returns results, markdown renders, wikilinks are clickable
- Tasks: list shows real TCUs from `tasks/active/`, status badges color-coded
- Skills: all 7 skills shown with metadata, "Run" button dispatches IPC call
- Logs: today's log file visible, scrollable, monospace font

---

### Task B4: Chat Panel + Pipeline Builder (Day 11-15)

**B4.1 Chat Panel** (`components/chat/ChatPanel.tsx`):
- Message input at bottom, messages scroll up
- Default model: executor (qwen3:4b) via Ollama
- Model selector toggle: Local (Ollama) / Claude (fallback)
- Send message flow:
  1. Extract intent (call `dispatch_tool` with `extract_intent`)
  2. Send to Ollama `/api/chat` endpoint (direct HTTP from Rust, not Python bridge)
  3. Display streamed response (Ollama streams by default)
  4. If response contains tool calls, dispatch them via `dispatch_tool` IPC
- `/skill <name>` command: runs skill inline, shows output in chat
- `/pipeline <name>` command: placeholder for Phase 3+
- Message history stored in Tauri app data dir (JSON file, not in Second Brain)

**New Rust code for Ollama streaming:**
Add `commands/chat.rs`:
- `send_chat(messages: String, model: String)` — calls Ollama `/api/chat`, streams response via Tauri events
- Frontend listens to `chat-stream` event, appends tokens to current message

**B4.2 Pipeline Builder** (`components/pipeline/PipelineBuilder.tsx`):
- Uses `@xyflow/react` (React Flow v12)
- Canvas with drag-and-drop node placement
- Node types (custom React Flow nodes):
  - **InputNode**: text field for user intent, file path, or URL
  - **AgentNode**: model selector dropdown + skill selector dropdown
  - **FunctionNode**: tool name dropdown (from `list_tools` IPC) + args JSON editor
  - **ConditionNode**: condition expression field + true/false output handles
  - **OutputNode**: output type selector (wiki update, file write, notification)
- Toolbar above canvas: Add Node (dropdown by type), Run Pipeline, Save Pipeline, Load Pipeline
- "Run Pipeline" button: serializes nodes + edges to JSON, calls `run_pipeline` IPC
- Node status indicators during run: gray (pending), blue (running), green (done), red (failed)
- Save/Load: pipelines stored as JSON in `~/.ashi/pipelines/`

**Pipeline execution in Rust** (`commands/pipeline.rs`):
- Topological sort of node graph
- Execute nodes sequentially (parallel nodes are Phase 3+)
- Each node: call appropriate IPC command based on node type
- Pass output of one node as input to connected nodes
- Emit `pipeline-progress` events so frontend can update node status

**Acceptance criteria:**
- Chat: send a message, get a response from Ollama, displayed with proper formatting
- Chat: model toggle switches between qwen3:4b and Claude
- Chat: `/skill research` runs the research skill with inline context
- Pipeline: can place 3+ nodes on canvas and connect them with edges
- Pipeline: "Run" executes nodes in order, status indicators update
- Pipeline: save/load roundtrips correctly (save, refresh, load = same graph)

---

## Execution Order Summary

```
Week 5:
  A1: skill_scorer.py                          [no deps]
  A2: ralph.py                                 [depends on A1]
  A3: tests for A1 + A2                        [depends on A1, A2]
  A4: cron setup                               [depends on A3 passing]

Week 6:
  B1: Tauri + React scaffold                   [no deps, parallel with A*]
  B2: Rust IPC + Python bridge                 [depends on B1]

Week 7:
  B3: Wiki, Tasks, Skills, Logs panels         [depends on B2]

Week 8:
  B4: Chat panel + Pipeline builder            [depends on B2, B3]
```

Tasks that can run in parallel:
- A1 and B1 (completely independent)
- B3.1 through B3.4 (independent panels, share only IPC layer from B2)

Tasks that are strictly sequential:
- A1 → A2 → A3 → A4
- B1 → B2 → B3 → B4

---

## Risk and Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Tauri v2 system deps fail on Ubuntu 24.04+ | Blocks Stream B | Install `libwebkit2gtk-4.1-dev` first. If GTK4 issues, use Tauri v2 beta with webkit2gtk-4.1 |
| Claude API rate limits during Ralph Loop | Weak skills not improved | Add exponential backoff. Process max 3 skills per run. Log and retry next night |
| React Flow performance with 50+ nodes | UI lag | Limit to 30 nodes per pipeline in v1. Virtualize in Phase 3 |
| Python subprocess latency from Rust | Slow IPC | Each call is ~100-300ms. Acceptable for v1. Phase 3: embed Python via PyO3 |
| 16GB RAM constraint | Can't run Tauri dev + Ollama + qwen3:4b simultaneously | Close Ollama models not in use. Tauri dev uses ~500MB. qwen3:4b uses ~3GB. Leaves headroom |

---

## Acceptance Criteria (Phase 2 Complete)

### Stream A Done When:
- [ ] `python -m functions.ralph --dry-run` runs and prints valid JSON
- [ ] 7 new tests pass (3 scorer + 4 ralph)
- [ ] All 52 tests pass (45 existing + 7 new)
- [ ] Cron entry installed and verified
- [ ] `skills/archive/` directory exists

### Stream B Done When:
- [ ] `cd app && npm run tauri dev` launches the desktop app
- [ ] Three-panel layout renders (sidebar, canvas, chat)
- [ ] Wiki search returns results and renders markdown
- [ ] Task monitor shows real TCUs with status badges
- [ ] Skills list shows all 7 skills with metadata
- [ ] Chat sends/receives messages via Ollama
- [ ] Pipeline builder: place nodes, connect edges, run pipeline, see status updates
- [ ] All IPC commands respond without error from frontend
