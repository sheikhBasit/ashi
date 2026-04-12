# ASHI — Design Specification
**Date:** 2026-04-07  
**Version:** 0.1  
**Status:** Draft — pending user approval  

> *Ashi (葦) — the thinking reed. Hollow enough to resonate, structured enough to sing.*

---

## Vision

ASHI is a self-improving local AI operating system. It runs your life, your work, and eventually your company — from one desktop app. Local models are the primary brain. Claude authors the skills and function tools that empower them. The Second Brain is the persistent memory. The Ralph Loop makes it better every day.

It will be open-sourced so anyone can run their entire operation from a single machine with no cloud dependency.

---

## Core Principle

```
Local model = decides WHAT to do
Skills/Functions = pre-written tools that DO it  
Second Brain = memory that prevents re-learning
Ralph Loop = daily self-improvement cycle
Claude = skill author + fallback brain
```

The local model never hallucinates on execution because it calls **pre-written, Claude-authored functions** — not generate code from scratch. Skills constrain the decision space. Second Brain gives context without burning tokens.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│               ASHI Desktop App (Tauri)               │
│  Pipeline Builder │ Chat Panel │ Wiki Viewer │ Logs  │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│              Orchestration Engine                    │
│   Node Graph Runner │ Task Queue │ Intent Tracker   │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                  Agent Layer                         │
│  deepseek-r1:8b (planner) │ qwen3:4b (executor)    │
│  qwen3:0.6b (router)      │ Claude (fallback/author)│
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│            Skills + Function Tools                   │
│  ingest_source │ search_wiki │ update_entity        │
│  run_pipeline  │ review_task │ create_skill         │
│  git_commit    │ web_search  │ send_notification    │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────┬───────────▼──────────┬─────────────────┐
│  MCP Layer │  Filesystem │ GitHub │ Obsidian │ Browser│
└────────────┴─────────────────────┴─────────────────-─┘
                         │
┌────────────────────────▼────────────────────────────┐
│              Second Brain (~/Desktop/SecondBrain/)   │
│  Wiki (LLM-maintained) │ Knowledge Graph            │
│  Intent Log │ Task Cognitive Units │ Skill Library  │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                  Ralph Loop                          │
│  Daily: review intent → judge work → improve skills │
└─────────────────────────────────────────────────────┘
```

---

## Key Concepts

### Task Cognitive Unit (TCU)
A single `task.md` file that is simultaneously:
- A **text** (human-readable intent + plan)
- A **program** (structured steps the agent executes)
- A **reflection** (the agent's own review of its work)

Structure:
```markdown
## Intent
What the user actually wanted (tracked from chat, not just the command)

## Plan
- [ ] Step 1
- [ ] Step 2

## Execution Log
timestamped record of what ran, what failed, what was skipped

## Judge Review
score, what went well, what to improve, wiki updates triggered

## Wiki Updates
which Second Brain pages were touched
```

### LLM Wiki (Second Brain layer)
Not RAG. The LLM **compiles** knowledge once and maintains it:
- `index.md` — catalog of all wiki pages
- `log.md` — append-only chronological record
- Entity pages, concept pages, synthesis pages
- Knowledge graph (Obsidian links = edges)
- Updated on every ingest, query, and task completion

### User Intent Tracking
Every chat message → intent extracted and logged:
```
[2026-04-07 16:30] intent: build ASHI desktop app | outcome: design spec written | satisfaction: pending
```
Review agent compares intent vs outcome weekly. Feeds the Ralph Loop.

### Ralph Loop
Daily autonomous cycle (3am cron):
1. Read intent log from past 24h
2. Review task outcomes vs intent
3. Judge: which skills underperformed?
4. Generate improved skill versions (via Claude)
5. Test new skills against past tasks
6. Promote winners, retire losers
7. Update wiki with learnings

### Skills
Pre-written Claude-authored instruction sets that constrain what local models do. A skill is:
- A markdown file with structured prompts
- Optionally backed by a function tool (shell/Python/JS)
- Versioned in the skill library
- Discoverable by the router model

### Function Tools
Python/JS/Bash functions with strict input/output contracts:
```python
def ingest_source(url: str, wiki_path: str) -> IngestResult:
    # fetch → extract → summarize → file into wiki → update index
    
def search_wiki(query: str, top_k: int = 5) -> list[WikiPage]:
    # BM25 + vector hybrid search over Second Brain

def update_entity(name: str, new_data: dict, wiki_path: str) -> None:
    # find entity page → merge new_data → update cross-references

def review_task(task_id: str) -> JudgeResult:
    # score: intent match, quality, side effects, wiki updates
```

---

## Phases

---

### Phase 0 — Foundation (Week 1–2)
**Goal:** Local brain working, Second Brain structured, basic CLI orchestration upgraded.

#### 0.1 Model Setup
- [ ] Pull all three models via cron (already scheduled for 8pm today)
- [ ] Set context windows: `num_ctx 16384` for deepseek-r1 and qwen3:4b
- [ ] Verify Ollama Anthropic-compatible endpoint at `localhost:11434`
- [ ] Test routing: deepseek-r1 for planning, qwen3:4b for tool calls

#### 0.2 Second Brain Structure
```
~/Desktop/SecondBrain/
├── wiki/                    ← LLM-maintained wiki
│   ├── index.md             ← master catalog
│   ├── log.md               ← append-only event log
│   ├── entities/            ← people, projects, tools
│   ├── concepts/            ← ideas, patterns, decisions
│   └── synthesis/           ← cross-source analysis
├── raw/                     ← immutable source documents
│   └── assets/              ← downloaded images
├── tasks/                   ← Task Cognitive Units
│   ├── active/
│   └── archive/
├── skills/                  ← skill library (versioned)
├── functions/               ← function tool implementations
├── intent-log.md            ← user intent tracker
└── knowledge-graph.md       ← graph overview
```

#### 0.3 Upgrade orchestrate-auto.sh
- [ ] Add Ollama as primary provider (before Gemini/OpenRouter)
- [ ] Replace hardcoded Quran app prompts with generic task prompts
- [ ] Add TCU generation: every run creates a `task.md` cognitive unit
- [ ] Add intent extraction step at the start of every orchestration
- [ ] Wire intent log append on every run

#### 0.4 Basic Wiki Operations (CLI)
- [ ] `ashi ingest <url|file>` — ingest source into wiki
- [ ] `ashi search <query>` — search wiki
- [ ] `ashi task <intent>` — create TCU and start orchestration
- [ ] `ashi lint` — wiki health check (orphans, contradictions, gaps)

**Deliverable:** Working CLI brain. Local models planning and executing tasks. Second Brain being populated.

---

### Phase 1 — Function Tools + Skill Library (Week 3–4)
**Goal:** Local models operate through structured functions, not freeform generation.

#### 1.1 Core Function Tools
Implement in Python with strict contracts:
- [ ] `ingest_source(url, wiki_path)` 
- [ ] `search_wiki(query, top_k)`
- [ ] `update_entity(name, data)`
- [ ] `create_tcu(intent, project)`
- [ ] `review_task(task_id)` — judge agent
- [ ] `append_intent_log(intent, outcome)`
- [ ] `run_skill(skill_name, context)`
- [ ] `lint_wiki(wiki_path)`

#### 1.2 Seed Skill Library
Claude authors first-pass skills for:
- [ ] `research` — web search + ingest into wiki
- [ ] `plan` — break intent into TCU steps
- [ ] `code` — implement with local model + function tools
- [ ] `review` — judge task output vs intent
- [ ] `ingest` — process raw source into wiki
- [ ] `daily-report` — summarize day into Second Brain
- [ ] `wiki-update` — maintain cross-references

#### 1.3 MCP Servers
- [ ] Filesystem MCP (already have)
- [ ] Obsidian MCP (`obsidian-mcp-server` — cyanheads)
- [ ] GitHub MCP
- [ ] Browser/search MCP (Brave Search or Playwright)

#### 1.4 Local Model Tool Calling
- [ ] Fix deepseek-r1 tool calling (use `MFDoom/deepseek-r1-tool-calling` fork on Ollama)
- [ ] Verify qwen3:4b native tool calling works
- [ ] Build tool dispatch layer: model outputs JSON → function router → execute → return result

**Deliverable:** Local models calling real functions. Skills constraining behaviour. MCP servers wired.

---

### Phase 2 — Desktop App: Core (Week 5–8)
**Goal:** Tauri desktop app with chat panel, wiki viewer, and basic pipeline builder.

#### 2.1 Tech Stack
```
Frontend:  React + TypeScript
UI:        shadcn/ui + Tailwind
Graph:     React Flow (pipeline builder)
Desktop:   Tauri v2 (Rust backend)
IPC:       Tauri commands (Rust ↔ JS)
Wiki:      Direct filesystem read (~/Desktop/SecondBrain/)
Obsidian:  Local REST API for bidirectional sync
```

#### 2.2 App Panels (Split-pane layout)
```
┌─────────────┬──────────────────┬──────────────┐
│  Sidebar    │   Main Canvas    │  Right Panel │
│             │                  │              │
│  - Projects │  Pipeline Builder│  Chat        │
│  - Tasks    │    OR            │  (local brain│
│  - Wiki     │  Wiki Viewer     │   + Claude   │
│  - Skills   │    OR            │   fallback)  │
│  - Logs     │  Task Monitor    │              │
└─────────────┴──────────────────┴──────────────┘
```

#### 2.3 Pipeline Builder (React Flow)
Node types:
- **Input** — user intent, file, URL, text
- **Agent** — local model with skill assigned
- **Function** — direct function tool call
- **Condition** — if/else routing
- **Parallel** — split into concurrent branches
- **Merge** — collect parallel results
- **Output** — wiki update, file write, notification

Each node has:
- Model selector (deepseek-r1 / qwen3:4b / Claude)
- Skill selector (dropdown from skill library)
- Function tool bindings
- Edit prompt inline
- Live status indicator during run

#### 2.4 Chat Panel
- Talks to local brain by default (deepseek-r1)
- Intent auto-extracted from every message → logged
- `/skill <name>` to invoke a skill inline
- `/pipeline <name>` to run a saved pipeline
- Model selector toggle (local / Claude)
- Context: current wiki page or task shown automatically

#### 2.5 Wiki Viewer
- Renders markdown from `~/Desktop/SecondBrain/wiki/`
- Bidirectional links clickable
- Knowledge graph visualization (D3 or Obsidian-style)
- Search bar → calls `search_wiki()` function
- "Edit in Obsidian" button → opens via Obsidian URI

**Deliverable:** Working desktop app. Chat with local brain. View wiki. Build and run basic pipelines.

---

### Phase 3 — Ralph Loop + Self-Improvement (Week 9–10)
**Goal:** System improves itself daily without you doing anything.

#### 3.1 Ralph Loop Cron (3am daily)
```bash
# Already in crontab structure — add:
0 3 * * * ~/Desktop/SecondBrain/skills/ralph-loop.sh >> ~/.logs/ralph-$(date +%Y-%m-%d).log 2>&1
```

Steps:
1. Read `intent-log.md` — last 24h entries
2. For each task: compare intent vs outcome (judge agent)
3. Score each skill used: did it help or hurt?
4. Low-scoring skills → Claude generates improved version
5. A/B test: run improved skill on yesterday's failed tasks
6. Promote if better, discard if not
7. Append findings to `wiki/log.md`
8. Send desktop notification with summary

#### 3.2 Skill Versioning
```
skills/
├── research/
│   ├── v1.md          ← retired
│   ├── v2.md          ← current
│   └── meta.json      ← score history, promotion dates
```

#### 3.3 Judge Agent
A dedicated review function that scores every TCU:
```json
{
  "task_id": "2026-04-07-build-feature-x",
  "intent_match": 0.87,
  "quality_score": 0.73,
  "skills_used": ["plan", "code", "review"],
  "skill_scores": {"plan": 0.9, "code": 0.6, "review": 0.8},
  "wiki_updated": true,
  "recommendation": "improve 'code' skill for Kotlin tasks"
}
```

**Deliverable:** System reviews its own work nightly. Skills improve automatically. You just check the morning summary.

---

### Phase 4 — Knowledge Graph + Advanced Wiki (Week 11–12)
**Goal:** Full LLM Wiki with knowledge graph, contradiction detection, and gap analysis.

#### 4.1 Knowledge Graph
- Every wiki entity/concept = node
- Every `[[link]]` = edge
- Stored as `knowledge-graph.json` (nodes + edges)
- Visualized in desktop app (D3 force-directed graph)
- Updated on every ingest and wiki edit

#### 4.2 Advanced Wiki Operations
- `ashi lint` detects:
  - Orphan pages (no inbound links)
  - Contradictions (same claim, different values, different dates)
  - Stale pages (source newer than last wiki update)
  - Missing entity pages (mentioned but no dedicated page)
  - Data gaps (suggests new sources to find)
- `ashi synthesize <topic>` — cross-source analysis → new wiki page
- `ashi compare <A> <B>` — comparison table → filed into wiki

#### 4.3 Obsidian Integration (Full)
- Local REST API + MCP server for bidirectional sync
- ASHI writes → Obsidian reflects in real time
- Obsidian Web Clipper → drops into `raw/` → auto-ingested
- Dataview frontmatter on all wiki pages (tags, source count, date)
- Graph view in Obsidian = visual complement to ASHI graph panel

**Deliverable:** Living, self-maintaining knowledge graph. Wiki gets smarter with every source and question.

---

### Phase 5 — Open Source + Plugin System (Week 13–16)
**Goal:** Package ASHI for anyone to install and extend.

#### 5.1 Plugin Architecture
```
ashi/
├── core/              ← engine, router, TCU, Ralph Loop
├── plugins/
│   ├── skills/        ← community skills
│   ├── functions/     ← community function tools
│   ├── pipelines/     ← shareable pipeline templates
│   └── mcps/          ← MCP server wrappers
├── desktop/           ← Tauri app
└── docs/
```

Plugin manifest (`plugin.json`):
```json
{
  "name": "ashi-research",
  "version": "1.0.0",
  "skills": ["research", "summarize"],
  "functions": ["web_search", "ingest_source"],
  "models": ["deepseek-r1:8b", "qwen3:4b"],
  "requires": ["brave-search-mcp"]
}
```

#### 5.2 One-Command Install
```bash
curl -fsSL https://ashi.dev/install.sh | bash
# Downloads Tauri app, sets up Ollama models, scaffolds Second Brain
```

#### 5.3 ASHI Hub
- Public registry for skills, function tools, pipelines
- Anyone submits → community rates → Ralph Loop tests
- Best skills auto-promoted to core

**Deliverable:** Open source repo. Anyone installs ASHI, picks their models, imports skills, and has a working local AI OS.

---

## Model Routing Logic

```
User intent arrives
       ↓
qwen3:0.6b classifies: [planning | coding | research | wiki | review]
       ↓
planning/wiki/review → deepseek-r1:8b (thinking mode ON)
coding/fast-tasks    → qwen3:4b (tool calling)
simple routing       → qwen3:0.6b stays
any model fails      → Claude fallback
       ↓
model selects skill from library
       ↓
model calls function tools (no freeform generation)
       ↓
result → TCU execution log → wiki update → intent log
```

---

## What Claude's Role Is

Claude does NOT run tasks. Claude:
1. **Authors skills** — writes the instruction sets that local models follow
2. **Authors function tools** — writes the Python/JS/Bash implementations
3. **Fallback brain** — handles tasks that exceed local model capability
4. **Ralph Loop contributor** — generates improved skill versions nightly

This is intentional. Claude's output becomes the rails that local models run on. The better Claude authors the skills, the less local models can hallucinate.

---

## Open Source Identity

- **Name:** ASHI
- **Tagline:** *The thinking reed. Local-first AI OS.*
- **Meaning:** Ashi (葦) — a reed, hollow enough to resonate
- **License:** MIT
- **Repo:** `github.com/basitdev/ashi` (or chosen namespace)
- **Install:** `npx ashi@latest init`

---

---

## Added Layers (v0.2 additions)

### Memory Architecture (4 layers)
```
Working Memory   → Valkey (Redis fork) — ephemeral per-task scratchpad
Episodic Memory  → Mem0 (self-hosted, Ollama backend) — "what happened when"
Semantic Memory  → Obsidian wiki + LanceDB vectors — "what is known"
Procedural Memory→ Skill library + outcome records — "how to do things"
Graph Memory     → Kuzu (embedded) — relationships between entities
```

### Storage Backend
- **LanceDB** — primary vector store (embedded, zero-copy, multimodal-ready)
- **Kuzu** — embedded graph DB (no server, Python/JS bindings, Apache 2.0)
- **sqlite-vec** — wiki index vectors (small, portable, one file)
- **SQLite** — relational metadata, task records, skill scores

### Observability Stack
- **Langfuse** (self-hosted Docker) — full LLM trace capture, eval scores, session grouping
- **Prometheus + Grafana** — agent metrics dashboard (tasks/hr, success rate, latency, model usage)
- **OpenTelemetry** — instrumentation standard across all TCU steps
- Key metrics: `ashi_tcu_duration_seconds`, `ashi_skill_score{skill}`, `ashi_model_tokens_total{model}`

### Evals Framework
- **DeepEval** (MIT, runs locally with Ollama judge) — per-TCU structured scoring
- Metrics: TaskCompletion, ToolCorrectness, AnswerRelevancy, Hallucination, custom G-Eval
- **LangChain AgentEvals** — trajectory scoring (was the sequence of tool calls correct?)
- Every TCU writes a test case → Ralph Loop runs `deepeval test run` nightly

### Crash Recovery
- **v1:** Step checkpointing (JSON file after each step, 50 lines Python) — zero dependencies
- **v2:** Temporal (self-hosted, SQLite backend) — full durable execution, resume from exact step
- TCU executor interface designed to be Temporal-compatible from day one

### Security Model
- **Skill sandboxing:** Bubblewrap (bwrap) — each skill runs in a namespaced sandbox with allowlisted paths
- **seccomp filter:** block dangerous syscalls (ptrace, mount, raw sockets) for skill processes
- **Input sanitization:** middleware layer strips prompt injection patterns before model sees user content
- **Structured outputs:** all agent outputs are typed JSON — free-text injection can't trigger tool calls
- **Secrets vault:** SQLCipher encrypted SQLite — skills request named secrets via API, never see raw values
- **MCP server trust:** pin versions, run community MCPs in containers with network isolation

### Context Management
- **Hierarchical summarization:** last 5 steps verbatim → older steps compressed → oldest = 1-paragraph abstract
- **LLMLingua-2:** Microsoft prompt compression, 3–6x token reduction, runs as separate BERT-scale model
- **Semantic caching:** GPTCache — skip tool calls with identical inputs from earlier in session
- **Context budget:** system prompt (500t) + wiki RAG (2000t) + history summary (500t) + task (remaining)
- **Hybrid search:** BM25 + cosine similarity, chunk size 512t with 64t overlap, top-5 re-ranked

### Voice Interface (Optional, Phase 3+)
- **STT:** whisper.cpp (`large-v3-turbo` INT8, ~800MB RAM, ~1s latency on CPU)
- **TTS:** Kokoro (82M params, Apache 2.0, `kokoro-fastapi` Docker container)
- **Unified:** Speaches Docker container (STT + TTS, single OpenAI-compatible endpoint)
- End-to-end latency on CPU: ~4–6 seconds (conversational with iGPU offload)

### Multimodal (Optional, Phase 4+)
- **LLaVA-Phi3** (3.8B, ~2.5GB) — default vision model, runs concurrently with primary
- **Qwen2.5-VL 7B** (~4.5GB) — stronger OCR, chart analysis (swap in when primary not loaded)
- Unlocks: screenshot debugging, PDF ingestion, diagram understanding

### Agent Protocol Layer
- **MCP** — tool integration (already in design)
- **A2A (Agent2Agent)** — each ASHI agent gets an Agent Card at `/.well-known/agent.json`
- **WebMCP** — browser agent integration (Chrome 146+) replacing DOM scraping

---

## Phase Summary Table

| Phase | Name | Duration | Deliverable |
|-------|------|----------|-------------|
| 0 | Foundation | Week 1–2 | Local brain, Obsidian Second Brain structured, CLI upgraded, Langfuse wired |
| 1 | Function Tools + Skills | Week 3–4 | Models calling functions, skill library, MCPs, LanceDB+Kuzu memory |
| 2 | Desktop App Core | Week 5–8 | Tauri app: chat + wiki viewer + pipeline builder, observability dashboard |
| 3 | Ralph Loop + Evals | Week 9–10 | Daily self-improvement, DeepEval scoring, skill versioning, voice interface |
| 4 | Knowledge Graph + Multimodal | Week 11–12 | Full graph, contradiction detection, vision model, Temporal crash recovery |
| 5 | Open Source | Week 13–16 | Plugin system, A2A agent cards, one-command install, ASHI Hub |

---

## Immediate Next Steps (This Week)

1. Models arrive at 8pm tonight (cron already set)
2. Set context windows on all three models
3. Restructure `~/Desktop/SecondBrain/` to match Phase 0.2 layout
4. Upgrade `orchestrate-auto.sh` to be generic + add TCU generation
5. Bootstrap `wiki/index.md` and `wiki/log.md`
6. Start Phase 0.4 CLI (`ashi` command)

---

*Spec written: 2026-04-07 | Next: implementation plan via writing-plans skill*
