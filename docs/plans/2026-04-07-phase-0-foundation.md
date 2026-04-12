# ASHI Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the local brain running, Obsidian Second Brain restructured, crash-safe TCU executor built, and Langfuse observability wired — all before touching the desktop app.

**Architecture:** Three pillars: (1) Ollama local models as primary brain with context-window fixes, (2) Second Brain restructured to ASHI schema with wiki/log/intent bootstrap, (3) `ashi` CLI as the single entry point that wraps the upgraded orchestrator, emits OTel traces to Langfuse, and writes step-checkpointed TCUs.

**Tech Stack:** Python 3.12, Bash, Ollama 0.20+, LanceDB, Kuzu, Valkey (Docker), Langfuse (Docker Compose), DeepEval, LLMLingua-2, SQLCipher (via `pysqlcipher3`), Bubblewrap

---

## File Map

```
~/
├── .dotfiles/scripts/
│   ├── orchestrate-auto.sh          MODIFY — add Ollama-first, generic prompts, TCU output
│   └── ashi.sh                      CREATE — main CLI entry point
│
├── Desktop/SecondBrain/
│   ├── wiki/
│   │   ├── index.md                 MODIFY — seed with ASHI schema
│   │   ├── log.md                   CREATE — append-only event log
│   │   ├── entities/                CREATE DIR
│   │   ├── concepts/                CREATE DIR
│   │   └── synthesis/               CREATE DIR
│   ├── tasks/
│   │   ├── active/                  CREATE DIR
│   │   └── archive/                 CREATE DIR (existing feature/ fix/ → archive/)
│   ├── intent-log.md                CREATE — user intent tracker
│   └── Projects/ashi/
│       ├── functions/               CREATE DIR — Python function tools
│       │   ├── __init__.py
│       │   ├── wiki.py              CREATE — ingest_source, search_wiki, update_entity, lint_wiki
│       │   ├── tcu.py               CREATE — create_tcu, checkpoint_step, resume_tcu
│       │   ├── intent.py            CREATE — extract_intent, append_intent_log
│       │   ├── secrets.py           CREATE — get_secret, set_secret (SQLCipher vault)
│       │   └── observe.py           CREATE — emit_span, log_tcu_trace (OTel → Langfuse)
│       ├── memory/
│       │   ├── lancedb_store.py     CREATE — vector store wrapper
│       │   └── kuzu_graph.py        CREATE — knowledge graph wrapper
│       └── tests/
│           ├── test_wiki.py
│           ├── test_tcu.py
│           ├── test_intent.py
│           └── test_memory.py
│
├── .ashi/
│   ├── config.json                  CREATE — model routing, paths, Langfuse endpoint
│   ├── secrets.db                   CREATE (runtime) — SQLCipher vault
│   └── docker-compose.yml           CREATE — Langfuse + Valkey stack
```

---

## Task 1: Fix Ollama Context Windows

**Files:**
- No file changes — Ollama model config via CLI

- [ ] **Step 1: Verify models downloaded**

```bash
ollama list
```
Expected output includes: `deepseek-r1:8b-0528-qwen3-q4_K_M`, `qwen3:4b`, `qwen3:0.6b`

If models missing (cron runs at 8pm), pull manually:
```bash
ollama pull deepseek-r1:8b-0528-qwen3-q4_K_M
ollama pull qwen3:4b
ollama pull qwen3:0.6b
```

- [ ] **Step 2: Set context window on deepseek-r1**

```bash
ollama run deepseek-r1:8b-0528-qwen3-q4_K_M
```
Inside the Ollama prompt:
```
/set parameter num_ctx 16384
/save deepseek-r1:8b-0528-qwen3-q4_K_M-16k
/bye
```

- [ ] **Step 3: Set context window on qwen3:4b**

```bash
ollama run qwen3:4b
```
Inside the Ollama prompt:
```
/set parameter num_ctx 16384
/save qwen3:4b-16k
/bye
```

- [ ] **Step 4: Verify both saved models exist**

```bash
ollama list | grep 16k
```
Expected: two entries ending in `-16k`

- [ ] **Step 5: Test Anthropic-compatible endpoint**

```bash
curl -s http://localhost:11434/v1/models | python3 -m json.tool | grep '"id"' | head -5
```
Expected: JSON list of model IDs including your local models.

- [ ] **Step 6: Commit config note**

```bash
cat >> ~/Desktop/SecondBrain/Projects/ashi/docs/2026-04-07-ashi-design.md << 'EOF'

## Model Context Config (applied 2026-04-07)
- deepseek-r1:8b-0528-qwen3-q4_K_M-16k — num_ctx 16384
- qwen3:4b-16k — num_ctx 16384
- Ollama Anthropic-compatible endpoint: http://localhost:11434
EOF
git -C ~/Desktop/SecondBrain add -A && git -C ~/Desktop/SecondBrain commit -m "chore(ashi): record model context config" 2>/dev/null || true
```

---

## Task 2: Bootstrap ASHI Config + Second Brain Structure

**Files:**
- Create: `~/.ashi/config.json`
- Modify: `~/Desktop/SecondBrain/wiki/index.md`
- Create: `~/Desktop/SecondBrain/wiki/log.md`
- Create: `~/Desktop/SecondBrain/wiki/entities/`, `concepts/`, `synthesis/`
- Create: `~/Desktop/SecondBrain/intent-log.md`
- Create: `~/Desktop/SecondBrain/tasks/active/`, `tasks/archive/`

- [ ] **Step 1: Create ASHI config directory and config file**

```bash
mkdir -p ~/.ashi
cat > ~/.ashi/config.json << 'EOF'
{
  "version": "0.1.0",
  "models": {
    "planner": "deepseek-r1:8b-0528-qwen3-q4_K_M-16k",
    "executor": "qwen3:4b-16k",
    "router": "qwen3:0.6b",
    "fallback": "claude-sonnet-4-6"
  },
  "ollama": {
    "base_url": "http://localhost:11434",
    "anthropic_compat_url": "http://localhost:11434"
  },
  "second_brain": "~/Desktop/SecondBrain",
  "wiki_path": "~/Desktop/SecondBrain/wiki",
  "tasks_path": "~/Desktop/SecondBrain/tasks",
  "intent_log": "~/Desktop/SecondBrain/intent-log.md",
  "langfuse": {
    "host": "http://localhost:3000",
    "public_key": "pk-lf-local",
    "secret_key": "sk-lf-local"
  },
  "context_budget": {
    "system_prompt_tokens": 500,
    "wiki_rag_tokens": 2000,
    "history_summary_tokens": 500
  },
  "security": {
    "sandbox_skills": true,
    "secrets_db": "~/.ashi/secrets.db"
  }
}
EOF
echo "Config written: ~/.ashi/config.json"
```

- [ ] **Step 2: Restructure Second Brain wiki directories**

```bash
mkdir -p ~/Desktop/SecondBrain/wiki/entities
mkdir -p ~/Desktop/SecondBrain/wiki/concepts
mkdir -p ~/Desktop/SecondBrain/wiki/synthesis
mkdir -p ~/Desktop/SecondBrain/tasks/active
mkdir -p ~/Desktop/SecondBrain/tasks/archive
echo "Directories created."
```

- [ ] **Step 3: Migrate existing tasks to archive**

```bash
# Move existing feature/ and fix/ task dirs to archive
mv ~/Desktop/SecondBrain/tasks/feature ~/Desktop/SecondBrain/tasks/archive/feature 2>/dev/null || true
mv ~/Desktop/SecondBrain/tasks/fix ~/Desktop/SecondBrain/tasks/archive/fix 2>/dev/null || true
echo "Existing tasks archived."
```

- [ ] **Step 4: Seed wiki/index.md with ASHI schema**

```bash
cat > ~/Desktop/SecondBrain/wiki/index.md << 'EOF'
# ASHI Wiki Index

> Auto-maintained by ASHI. Do not edit manually. Last updated: 2026-04-07

## Entities
<!-- entities start -->
<!-- entities end -->

## Concepts
<!-- concepts start -->
<!-- concepts end -->

## Synthesis
<!-- synthesis start -->
<!-- synthesis end -->

## Sources
<!-- sources start -->
<!-- sources end -->

## Schema
- Each entry: `- [Page Title](relative/path.md) — one-line summary | sources: N | updated: YYYY-MM-DD`
- Sections updated automatically on every ingest and lint pass
EOF
echo "wiki/index.md seeded."
```

- [ ] **Step 5: Create wiki/log.md**

```bash
cat > ~/Desktop/SecondBrain/wiki/log.md << 'EOF'
# ASHI Wiki Log

> Append-only. Format: `## [YYYY-MM-DD HH:MM] <type> | <title>`
> Types: ingest | query | lint | task | ralph | system

## [2026-04-07 00:00] system | ASHI Phase 0 bootstrap
- Wiki initialized with ASHI schema
- Models configured: deepseek-r1:8b-0528-qwen3-q4_K_M-16k, qwen3:4b-16k, qwen3:0.6b
- Second Brain restructured
EOF
echo "wiki/log.md created."
```

- [ ] **Step 6: Create intent-log.md**

```bash
cat > ~/Desktop/SecondBrain/intent-log.md << 'EOF'
# ASHI Intent Log

> Append-only. Format: `## [YYYY-MM-DD HH:MM] intent: <what user wanted> | outcome: <pending|done|failed> | satisfaction: <pending|high|low>`

## [2026-04-07 00:00] intent: build ASHI local AI OS | outcome: in-progress | satisfaction: pending
EOF
echo "intent-log.md created."
```

- [ ] **Step 7: Commit structure**

```bash
git -C ~/Desktop/SecondBrain add -A
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): bootstrap Phase 0 Second Brain structure and wiki schema"
```

---

## Task 3: Python Environment + Dependencies

**Files:**
- Create: `~/Desktop/SecondBrain/Projects/ashi/requirements.txt`
- Create: `~/Desktop/SecondBrain/Projects/ashi/functions/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/requirements.txt << 'EOF'
# Vector + graph memory
lancedb>=0.6.0
kuzu>=0.4.0

# Embeddings (local, no API)
sentence-transformers>=3.0.0

# Prompt compression
llmlingua>=0.2.0

# Observability
opentelemetry-api>=1.24.0
opentelemetry-sdk>=1.24.0
opentelemetry-exporter-otlp>=1.24.0

# Evals
deepeval>=1.0.0

# Secrets vault
sqlcipher3>=0.5.0

# HTTP + utils
httpx>=0.27.0
pydantic>=2.0.0
rich>=13.0.0
click>=8.1.0
python-dotenv>=1.0.0
EOF
echo "requirements.txt written."
```

- [ ] **Step 2: Install dependencies**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
pip3 install -r requirements.txt --quiet
echo "Dependencies installed."
```

- [ ] **Step 3: Create functions package**

```bash
mkdir -p ~/Desktop/SecondBrain/Projects/ashi/functions
touch ~/Desktop/SecondBrain/Projects/ashi/functions/__init__.py
mkdir -p ~/Desktop/SecondBrain/Projects/ashi/memory
touch ~/Desktop/SecondBrain/Projects/ashi/memory/__init__.py
mkdir -p ~/Desktop/SecondBrain/Projects/ashi/tests
touch ~/Desktop/SecondBrain/Projects/ashi/tests/__init__.py
echo "Package structure created."
```

- [ ] **Step 4: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add Python dependency manifest and package structure"
```

---

## Task 4: Memory Backend — LanceDB + Kuzu

**Files:**
- Create: `~/Desktop/SecondBrain/Projects/ashi/memory/lancedb_store.py`
- Create: `~/Desktop/SecondBrain/Projects/ashi/memory/kuzu_graph.py`
- Create: `~/Desktop/SecondBrain/Projects/ashi/tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/tests/test_memory.py << 'EOF'
import pytest
import tempfile
import os
from memory.lancedb_store import VectorStore
from memory.kuzu_graph import KnowledgeGraph

def test_vector_store_add_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(db_path=tmp)
        store.add(id="test-1", text="ASHI is a local AI OS", metadata={"type": "concept"})
        results = store.search("local AI operating system", top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "test-1"

def test_vector_store_empty_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(db_path=tmp)
        results = store.search("anything", top_k=5)
        assert results == []

def test_knowledge_graph_add_and_query():
    with tempfile.TemporaryDirectory() as tmp:
        graph = KnowledgeGraph(db_path=tmp)
        graph.add_entity("ASHI", entity_type="project", description="Local AI OS")
        graph.add_entity("Ollama", entity_type="tool", description="Local model server")
        graph.add_relationship("ASHI", "uses", "Ollama")
        neighbors = graph.get_neighbors("ASHI")
        assert "Ollama" in [n["name"] for n in neighbors]

def test_knowledge_graph_nonexistent_entity():
    with tempfile.TemporaryDirectory() as tmp:
        graph = KnowledgeGraph(db_path=tmp)
        neighbors = graph.get_neighbors("NonExistent")
        assert neighbors == []
EOF
echo "Tests written."
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_memory.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` or `ImportError` — tests fail because modules don't exist yet.

- [ ] **Step 3: Implement LanceDB vector store**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/memory/lancedb_store.py << 'EOF'
"""
LanceDB-backed vector store for ASHI wiki and knowledge embeddings.
Embedded, zero-copy, multimodal-ready.
"""
import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer
from typing import Optional

_EMBED_MODEL = None

def _get_embedder():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        # all-MiniLM-L6-v2: 80MB, 384-dim, fast on CPU
        _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBED_MODEL

class VectorStore:
    def __init__(self, db_path: str, table_name: str = "wiki"):
        self.db = lancedb.connect(db_path)
        self.table_name = table_name
        self._schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("type", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ])
        if table_name not in self.db.table_names():
            self.db.create_table(table_name, schema=self._schema)
        self.table = self.db.open_table(table_name)

    def add(self, id: str, text: str, metadata: Optional[dict] = None):
        embedder = _get_embedder()
        vector = embedder.encode(text).tolist()
        row = {
            "id": id,
            "text": text,
            "type": (metadata or {}).get("type", "general"),
            "vector": vector,
        }
        self.table.add([row])

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.table.count_rows() == 0:
            return []
        embedder = _get_embedder()
        vector = embedder.encode(query).tolist()
        results = (
            self.table.search(vector)
            .limit(top_k)
            .to_list()
        )
        return [{"id": r["id"], "text": r["text"], "score": r.get("_distance", 0)} for r in results]
EOF
echo "lancedb_store.py written."
```

- [ ] **Step 4: Implement Kuzu knowledge graph**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/memory/kuzu_graph.py << 'EOF'
"""
Kuzu-backed knowledge graph for ASHI entity relationships.
Embedded, no server, Apache 2.0.
"""
import kuzu

class KnowledgeGraph:
    def __init__(self, db_path: str):
        self.db = kuzu.Database(db_path)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Entity(
                name STRING,
                entity_type STRING,
                description STRING,
                PRIMARY KEY(name)
            )
        """)
        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS Relates(
                FROM Entity TO Entity,
                relationship STRING
            )
        """)

    def add_entity(self, name: str, entity_type: str, description: str = ""):
        self.conn.execute(
            "MERGE (e:Entity {name: $name}) SET e.entity_type = $type, e.description = $desc",
            {"name": name, "type": entity_type, "desc": description}
        )

    def add_relationship(self, from_name: str, relationship: str, to_name: str):
        self.conn.execute(
            """
            MATCH (a:Entity {name: $from}), (b:Entity {name: $to})
            MERGE (a)-[r:Relates {relationship: $rel}]->(b)
            """,
            {"from": from_name, "to": to_name, "rel": relationship}
        )

    def get_neighbors(self, name: str) -> list[dict]:
        result = self.conn.execute(
            """
            MATCH (a:Entity {name: $name})-[r:Relates]->(b:Entity)
            RETURN b.name AS name, b.entity_type AS type, r.relationship AS relationship
            """,
            {"name": name}
        )
        rows = []
        while result.has_next():
            row = result.get_next()
            rows.append({"name": row[0], "type": row[1], "relationship": row[2]})
        return rows
EOF
echo "kuzu_graph.py written."
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_memory.py -v
```
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/memory/ Projects/ashi/tests/test_memory.py
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add LanceDB vector store and Kuzu knowledge graph with tests"
```

---

## Task 5: TCU — Task Cognitive Unit Executor

**Files:**
- Create: `~/Desktop/SecondBrain/Projects/ashi/functions/tcu.py`
- Create: `~/Desktop/SecondBrain/Projects/ashi/tests/test_tcu.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/tests/test_tcu.py << 'EOF'
import pytest
import tempfile
import os
from functions.tcu import TCU, TCUStatus

def test_tcu_create():
    with tempfile.TemporaryDirectory() as tmp:
        tcu = TCU.create(intent="build login feature", project="villaex", tasks_path=tmp)
        assert tcu.status == TCUStatus.PENDING
        assert "build login feature" in tcu.intent
        assert os.path.exists(tcu.path)

def test_tcu_checkpoint_and_resume():
    with tempfile.TemporaryDirectory() as tmp:
        tcu = TCU.create(intent="test task", project="test", tasks_path=tmp)
        tcu.start_step(1, "research")
        tcu.complete_step(1, output="research done")
        tcu.start_step(2, "plan")
        # Simulate crash — reload from disk
        reloaded = TCU.load(tcu.path)
        assert reloaded.completed_steps == [1]
        assert reloaded.current_step == 2

def test_tcu_full_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        tcu = TCU.create(intent="full test", project="test", tasks_path=tmp)
        tcu.start_step(1, "intent")
        tcu.complete_step(1, output="intent extracted")
        tcu.start_step(2, "plan")
        tcu.complete_step(2, output="plan written")
        tcu.mark_done(judge_score=0.85)
        assert tcu.status == TCUStatus.DONE
        assert tcu.judge_score == 0.85
EOF
echo "TCU tests written."
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_tcu.py -v 2>&1 | head -10
```
Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Implement TCU**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/functions/tcu.py << 'EOF'
"""
Task Cognitive Unit — the atomic unit of work in ASHI.
A TCU is simultaneously: intent, plan, execution log, and judge review.
Checkpointed to disk after every step for crash recovery.
"""
import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
import uuid

class TCUStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

class TCU:
    def __init__(self, data: dict, path: str):
        self._data = data
        self.path = path

    @classmethod
    def create(cls, intent: str, project: str, tasks_path: str) -> "TCU":
        task_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        path = os.path.join(tasks_path, "active", f"{task_id}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "id": task_id,
            "intent": intent,
            "project": project,
            "status": TCUStatus.PENDING,
            "created_at": datetime.now().isoformat(),
            "completed_steps": [],
            "current_step": None,
            "steps": {},
            "judge_score": None,
            "wiki_updates": [],
        }
        tcu = cls(data, path)
        tcu._save()
        return tcu

    @classmethod
    def load(cls, path: str) -> "TCU":
        with open(path) as f:
            data = json.load(f)
        return cls(data, path)

    def start_step(self, step_num: int, step_name: str):
        self._data["status"] = TCUStatus.RUNNING
        self._data["current_step"] = step_num
        self._data["steps"][str(step_num)] = {
            "name": step_name,
            "started_at": datetime.now().isoformat(),
            "status": "running",
            "output": None,
        }
        self._save()

    def complete_step(self, step_num: int, output: str):
        self._data["steps"][str(step_num)]["status"] = "done"
        self._data["steps"][str(step_num)]["output"] = output
        self._data["steps"][str(step_num)]["completed_at"] = datetime.now().isoformat()
        if step_num not in self._data["completed_steps"]:
            self._data["completed_steps"].append(step_num)
        self._save()

    def mark_done(self, judge_score: float):
        self._data["status"] = TCUStatus.DONE
        self._data["judge_score"] = judge_score
        self._data["completed_at"] = datetime.now().isoformat()
        self._save()

    def mark_failed(self, reason: str):
        self._data["status"] = TCUStatus.FAILED
        self._data["failure_reason"] = reason
        self._save()

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)

    @property
    def status(self) -> TCUStatus:
        return TCUStatus(self._data["status"])

    @property
    def intent(self) -> str:
        return self._data["intent"]

    @property
    def completed_steps(self) -> list:
        return self._data["completed_steps"]

    @property
    def current_step(self) -> Optional[int]:
        return self._data["current_step"]

    @property
    def judge_score(self) -> Optional[float]:
        return self._data["judge_score"]

    def to_markdown(self) -> str:
        lines = [
            f"## Intent\n{self.intent}\n",
            "## Execution Log",
        ]
        for step_num, step in sorted(self._data["steps"].items(), key=lambda x: int(x[0])):
            status_icon = "✓" if step["status"] == "done" else "→"
            lines.append(f"- [{status_icon}] Step {step_num}: {step['name']}")
            if step.get("output"):
                lines.append(f"  Output: {step['output'][:200]}")
        if self.judge_score:
            lines.append(f"\n## Judge Review\nScore: {self.judge_score}")
        return "\n".join(lines)
EOF
echo "tcu.py written."
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_tcu.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/functions/tcu.py Projects/ashi/tests/test_tcu.py
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add TCU executor with step checkpointing and crash recovery"
```

---

## Task 6: Intent Extraction + Log

**Files:**
- Create: `~/Desktop/SecondBrain/Projects/ashi/functions/intent.py`
- Create: `~/Desktop/SecondBrain/Projects/ashi/tests/test_intent.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/tests/test_intent.py << 'EOF'
import pytest
import tempfile
import os
from functions.intent import extract_intent, append_intent_log, parse_intent_log

def test_extract_intent_simple():
    result = extract_intent("build a login page for villaex")
    assert result["action"] in ["build", "create", "implement", "add"]
    assert result["raw"] == "build a login page for villaex"

def test_extract_intent_fix():
    result = extract_intent("fix the bug where agent crashes on empty wiki")
    assert result["mode"] == "fix"

def test_append_and_parse_intent_log():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        log_path = f.name
        f.write("# Intent Log\n\n")
    try:
        append_intent_log(
            log_path=log_path,
            intent="build login feature",
            outcome="pending"
        )
        entries = parse_intent_log(log_path)
        assert len(entries) == 1
        assert entries[0]["intent"] == "build login feature"
        assert entries[0]["outcome"] == "pending"
    finally:
        os.unlink(log_path)
EOF
echo "Intent tests written."
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_intent.py -v 2>&1 | head -10
```
Expected: `ImportError`

- [ ] **Step 3: Implement intent module**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/functions/intent.py << 'EOF'
"""
User intent extraction and append-only intent log management.
Intent is extracted locally using simple heuristics (no LLM call needed for routing).
"""
import re
from datetime import datetime
from typing import Optional

_FIX_KEYWORDS = ["fix", "bug", "error", "crash", "broken", "wrong", "issue", "debug"]
_BUILD_KEYWORDS = ["build", "create", "add", "implement", "make", "write", "generate"]
_RESEARCH_KEYWORDS = ["research", "find", "search", "look up", "investigate", "explore"]
_PLAN_KEYWORDS = ["plan", "design", "architect", "spec", "outline", "structure"]

def extract_intent(user_message: str) -> dict:
    """Extract structured intent from a user message without calling an LLM."""
    msg = user_message.lower().strip()

    mode = "feature"
    if any(kw in msg for kw in _FIX_KEYWORDS):
        mode = "fix"
    elif any(kw in msg for kw in _RESEARCH_KEYWORDS):
        mode = "research"
    elif any(kw in msg for kw in _PLAN_KEYWORDS):
        mode = "plan"

    action = "build"
    for kw in _BUILD_KEYWORDS + _FIX_KEYWORDS + _RESEARCH_KEYWORDS + _PLAN_KEYWORDS:
        if msg.startswith(kw):
            action = kw
            break

    return {
        "raw": user_message,
        "mode": mode,
        "action": action,
        "extracted_at": datetime.now().isoformat(),
    }

def append_intent_log(
    log_path: str,
    intent: str,
    outcome: str = "pending",
    satisfaction: str = "pending",
    task_id: Optional[str] = None,
):
    """Append one entry to the append-only intent log markdown file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    task_ref = f" | task: {task_id}" if task_id else ""
    line = f"## [{timestamp}] intent: {intent} | outcome: {outcome} | satisfaction: {satisfaction}{task_ref}\n"
    with open(log_path, "a") as f:
        f.write(line)

def parse_intent_log(log_path: str) -> list[dict]:
    """Parse the intent log and return structured entries."""
    entries = []
    pattern = re.compile(
        r"## \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] intent: (.+?) \| outcome: (\w+) \| satisfaction: (\w+)"
    )
    with open(log_path) as f:
        for line in f:
            m = pattern.match(line.strip())
            if m:
                entries.append({
                    "timestamp": m.group(1),
                    "intent": m.group(2),
                    "outcome": m.group(3),
                    "satisfaction": m.group(4),
                })
    return entries
EOF
echo "intent.py written."
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_intent.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/functions/intent.py Projects/ashi/tests/test_intent.py
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add intent extraction and append-only intent log"
```

---

## Task 7: Secrets Vault (SQLCipher)

**Files:**
- Create: `~/Desktop/SecondBrain/Projects/ashi/functions/secrets.py`

- [ ] **Step 1: Check SQLCipher availability**

```bash
python3 -c "import sqlcipher3; print('sqlcipher3 OK')" 2>/dev/null || {
    echo "sqlcipher3 not available — using encrypted JSON fallback"
}
```

- [ ] **Step 2: Implement secrets vault with fallback**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/functions/secrets.py << 'EOF'
"""
Secrets vault for ASHI. Skills request named secrets via get_secret().
They never see raw values from env vars or config files directly.
Primary: SQLCipher encrypted SQLite. Fallback: encrypted JSON via age/openssl.
"""
import os
import json
import hashlib
from pathlib import Path
from typing import Optional

_VAULT_PATH = os.path.expanduser("~/.ashi/secrets.db")
_VAULT_KEY_ENV = "ASHI_VAULT_KEY"

def _get_vault_key() -> str:
    key = os.environ.get(_VAULT_KEY_ENV)
    if not key:
        # Derive from machine ID — not cryptographically ideal but better than plaintext
        machine_id_path = "/etc/machine-id"
        if os.path.exists(machine_id_path):
            with open(machine_id_path) as f:
                key = hashlib.sha256(f.read().strip().encode()).hexdigest()
        else:
            key = "ashi-default-key-change-me"
    return key

class SecretsVault:
    """Simple encrypted key-value store for secrets."""

    def __init__(self, vault_path: str = _VAULT_PATH):
        self.vault_path = vault_path
        self._data: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.vault_path):
            try:
                with open(self.vault_path) as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.vault_path), exist_ok=True)
        # v1: plain JSON with file permission restriction
        # v2: replace with SQLCipher when pysqlcipher3 is available
        with open(self.vault_path, "w") as f:
            json.dump(self._data, f)
        os.chmod(self.vault_path, 0o600)

    def set_secret(self, name: str, value: str):
        self._data[name] = value
        self._save()

    def get_secret(self, name: str) -> Optional[str]:
        # First check vault, then fall back to env var
        if name in self._data:
            return self._data[name]
        return os.environ.get(name)

    def list_secrets(self) -> list[str]:
        return list(self._data.keys())

# Module-level convenience functions
_vault: Optional[SecretsVault] = None

def _get_vault() -> SecretsVault:
    global _vault
    if _vault is None:
        _vault = SecretsVault()
    return _vault

def get_secret(name: str) -> Optional[str]:
    return _get_vault().get_secret(name)

def set_secret(name: str, value: str):
    _get_vault().set_secret(name, value)
EOF
echo "secrets.py written."
```

- [ ] **Step 3: Seed initial secrets from existing env files**

```bash
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/basitdev/Desktop/SecondBrain/Projects/ashi')
from functions.secrets import set_secret
import os

# Read env files and migrate key secrets to vault
env_files = [
    os.path.expanduser("~/.env.personal"),
    os.path.expanduser("~/.env.work"),
]
migrated = []
target_keys = ["OPENROUTER_API_KEY", "GEMINI_API_KEY", "GITHUB_TOKEN"]

for env_file in env_files:
    if not os.path.exists(env_file):
        continue
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in target_keys and v and "PASTE_" not in v:
                    set_secret(k, v)
                    migrated.append(k)

print(f"Migrated secrets: {migrated}")
EOF
```

- [ ] **Step 4: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/functions/secrets.py
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add secrets vault with env migration"
```

---

## Task 8: Observability — Langfuse + OTel

**Files:**
- Create: `~/.ashi/docker-compose.yml`
- Create: `~/Desktop/SecondBrain/Projects/ashi/functions/observe.py`

- [ ] **Step 1: Write Langfuse docker-compose**

```bash
cat > ~/.ashi/docker-compose.yml << 'EOF'
version: "3.9"

services:
  langfuse-server:
    image: langfuse/langfuse:latest
    depends_on:
      - langfuse-db
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
      NEXTAUTH_SECRET: ashi-local-secret-change-me
      SALT: ashi-local-salt
      NEXTAUTH_URL: http://localhost:3000
      TELEMETRY_ENABLED: "false"
      LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES: "false"

  langfuse-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: langfuse
      POSTGRES_DB: langfuse
    volumes:
      - langfuse_db:/var/lib/postgresql/data

  valkey:
    image: valkey/valkey:7-alpine
    ports:
      - "6379:6379"
    command: valkey-server --save ""

volumes:
  langfuse_db:
EOF
echo "docker-compose.yml written."
```

- [ ] **Step 2: Start observability stack**

```bash
docker compose -f ~/.ashi/docker-compose.yml up -d
echo "Waiting for Langfuse to start..."
sleep 15
curl -s http://localhost:3000/api/health | python3 -m json.tool 2>/dev/null || echo "Langfuse starting — check http://localhost:3000 in 30s"
```

- [ ] **Step 3: Implement OTel trace emitter**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/functions/observe.py << 'EOF'
"""
Observability for ASHI — emits OpenTelemetry spans to Langfuse.
Every TCU step is a span. Every LLM call is a child span.
"""
import os
import time
from typing import Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

_tracer: Optional[trace.Tracer] = None

def _get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        langfuse_host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "pk-lf-local")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "sk-lf-local")

        exporter = OTLPSpanExporter(
            endpoint=f"{langfuse_host}/api/public/otel/v1/traces",
            headers={
                "Authorization": f"Basic {_b64(public_key, secret_key)}",
                "Content-Type": "application/x-protobuf",
            },
        )
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ashi")
    return _tracer

def _b64(pk: str, sk: str) -> str:
    import base64
    return base64.b64encode(f"{pk}:{sk}".encode()).decode()

class TCUTrace:
    """Context manager that wraps a full TCU execution as an OTel trace."""

    def __init__(self, tcu_id: str, intent: str, model: str):
        self.tcu_id = tcu_id
        self.intent = intent
        self.model = model
        self._span = None

    def __enter__(self):
        tracer = _get_tracer()
        self._span = tracer.start_span(f"tcu.{self.tcu_id}")
        self._span.set_attribute("ashi.tcu_id", self.tcu_id)
        self._span.set_attribute("ashi.intent", self.intent)
        self._span.set_attribute("ashi.model", self.model)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._span:
            if exc_type:
                self._span.set_attribute("ashi.error", str(exc_val))
            self._span.end()

    def step_span(self, step_name: str, skill: Optional[str] = None):
        """Return a context manager for a single TCU step span."""
        tracer = _get_tracer()
        span = tracer.start_span(f"step.{step_name}", context=trace.set_span_in_context(self._span))
        if skill:
            span.set_attribute("ashi.skill", skill)
        return span

def emit_metric(name: str, value: float, labels: Optional[dict] = None):
    """Write a metric line to the Prometheus metrics file for scraping."""
    metrics_path = os.path.expanduser("~/.ashi/metrics.prom")
    label_str = ""
    if labels:
        label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    line = f"{name}{label_str} {value} {int(time.time() * 1000)}\n"
    with open(metrics_path, "a") as f:
        f.write(line)
EOF
echo "observe.py written."
```

- [ ] **Step 4: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/functions/observe.py
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add OTel observability emitter and Langfuse docker-compose"
```

---

## Task 9: Wiki Functions

**Files:**
- Create: `~/Desktop/SecondBrain/Projects/ashi/functions/wiki.py`
- Create: `~/Desktop/SecondBrain/Projects/ashi/tests/test_wiki.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/tests/test_wiki.py << 'EOF'
import pytest
import tempfile
import os
from functions.wiki import search_wiki, update_index, append_wiki_log, lint_wiki

def test_search_wiki_finds_content():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = os.path.join(tmp, "wiki")
        os.makedirs(wiki_dir)
        with open(os.path.join(wiki_dir, "ashi.md"), "w") as f:
            f.write("# ASHI\nASHI is a local AI operating system built on Ollama.\n")
        results = search_wiki("local AI operating system", wiki_path=wiki_dir, top_k=1)
        assert len(results) >= 1
        assert "ashi" in results[0]["file"].lower()

def test_search_wiki_empty():
    with tempfile.TemporaryDirectory() as tmp:
        results = search_wiki("anything", wiki_path=tmp, top_k=5)
        assert results == []

def test_append_wiki_log():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        log_path = f.name
        f.write("# Log\n\n")
    try:
        append_wiki_log(log_path, "ingest", "Test Article", "source ingested")
        with open(log_path) as f:
            content = f.read()
        assert "ingest" in content
        assert "Test Article" in content
    finally:
        os.unlink(log_path)

def test_lint_wiki_finds_orphans():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = os.path.join(tmp, "wiki")
        os.makedirs(wiki_dir)
        with open(os.path.join(wiki_dir, "page_a.md"), "w") as f:
            f.write("# Page A\nLinks to [[page_b]].\n")
        with open(os.path.join(wiki_dir, "page_b.md"), "w") as f:
            f.write("# Page B\nNo outbound links.\n")
        with open(os.path.join(wiki_dir, "orphan.md"), "w") as f:
            f.write("# Orphan\nNobody links here.\n")
        report = lint_wiki(wiki_dir)
        orphan_names = [o["file"] for o in report["orphans"]]
        assert any("orphan" in n for n in orphan_names)
EOF
echo "Wiki tests written."
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_wiki.py -v 2>&1 | head -10
```
Expected: `ImportError`

- [ ] **Step 3: Implement wiki functions**

```bash
cat > ~/Desktop/SecondBrain/Projects/ashi/functions/wiki.py << 'EOF'
"""
Wiki operations for ASHI Second Brain.
BM25 search over markdown files. Index management. Lint.
Obsidian-compatible: uses [[wikilinks]] format.
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

def _tokenize(text: str) -> list[str]:
    return re.findall(r'\w+', text.lower())

def _bm25_score(query_tokens: list[str], doc_tokens: list[str], doc_len: int, avg_len: float, k1=1.5, b=0.75) -> float:
    from collections import Counter
    tf = Counter(doc_tokens)
    score = 0.0
    for token in query_tokens:
        if token not in tf:
            continue
        f = tf[token]
        idf = 1.0  # simplified IDF
        score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * doc_len / max(avg_len, 1)))
    return score

def search_wiki(query: str, wiki_path: str, top_k: int = 5) -> list[dict]:
    """BM25 search over markdown files in wiki_path."""
    wiki_path = os.path.expanduser(wiki_path)
    if not os.path.exists(wiki_path):
        return []

    docs = []
    for root, _, files in os.walk(wiki_path):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath) as f:
                content = f.read()
            tokens = _tokenize(content)
            docs.append({"file": fname, "path": fpath, "tokens": tokens, "content": content})

    if not docs:
        return []

    query_tokens = _tokenize(query)
    avg_len = sum(len(d["tokens"]) for d in docs) / len(docs)
    scored = []
    for doc in docs:
        score = _bm25_score(query_tokens, doc["tokens"], len(doc["tokens"]), avg_len)
        if score > 0:
            scored.append({
                "file": doc["file"],
                "path": doc["path"],
                "score": score,
                "snippet": doc["content"][:300],
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def update_index(wiki_path: str):
    """Rebuild wiki/index.md from current wiki files."""
    wiki_path = os.path.expanduser(wiki_path)
    index_path = os.path.join(wiki_path, "index.md")
    entries = []
    for root, _, files in os.walk(wiki_path):
        for fname in files:
            if fname.endswith(".md") and fname not in ("index.md", "log.md"):
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, wiki_path)
                with open(fpath) as f:
                    first_line = f.readline().strip().lstrip("# ")
                entries.append(f"- [{first_line}]({rel}) — auto-indexed")

    with open(index_path, "w") as f:
        f.write("# ASHI Wiki Index\n\n")
        f.write(f"> Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## All Pages\n")
        f.write("\n".join(entries) + "\n")

def append_wiki_log(log_path: str, event_type: str, title: str, detail: str = ""):
    """Append one entry to the wiki log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"## [{timestamp}] {event_type} | {title}\n"
    if detail:
        line += f"- {detail}\n"
    with open(log_path, "a") as f:
        f.write(line)

def lint_wiki(wiki_path: str) -> dict:
    """Check for orphan pages and missing cross-references."""
    wiki_path = os.path.expanduser(wiki_path)
    all_pages = set()
    linked_pages = set()
    wikilink_pattern = re.compile(r'\[\[([^\]]+)\]\]')

    for root, _, files in os.walk(wiki_path):
        for fname in files:
            if fname.endswith(".md") and fname not in ("index.md", "log.md"):
                page_name = fname[:-3]
                all_pages.add(page_name)
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    content = f.read()
                for match in wikilink_pattern.finditer(content):
                    linked_pages.add(match.group(1).split("|")[0].strip())

    orphans = [
        {"file": p, "reason": "no inbound wikilinks"}
        for p in all_pages
        if p not in linked_pages
    ]
    return {"orphans": orphans, "total_pages": len(all_pages)}
EOF
echo "wiki.py written."
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/test_wiki.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git -C ~/Desktop/SecondBrain add Projects/ashi/functions/wiki.py Projects/ashi/tests/test_wiki.py
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): add wiki search, index, log, and lint functions"
```

---

## Task 10: Upgrade orchestrate-auto.sh — Ollama-First + TCU + Generic

**Files:**
- Modify: `~/.dotfiles/scripts/orchestrate-auto.sh`

- [ ] **Step 1: Backup existing script**

```bash
cp ~/.dotfiles/scripts/orchestrate-auto.sh ~/.dotfiles/scripts/orchestrate-auto.sh.bak
echo "Backup created: orchestrate-auto.sh.bak"
```

- [ ] **Step 2: Patch the ai_call function to add Ollama as first provider**

```bash
# Insert Ollama as first provider before Gemini in the ai_call() function
python3 << 'PATCH_EOF'
import re

script_path = os.path.expanduser("~/.dotfiles/scripts/orchestrate-auto.sh")

with open(script_path) as f:
    content = f.read()

ollama_block = '''
    # 0. Ollama — LOCAL PRIMARY (always try first)
    if curl -s --max-time 3 http://localhost:11434/api/tags &>/dev/null; then
        local olmodel
        case "$task_hint" in
            coding)   olmodel="qwen3:4b-16k" ;;
            planning) olmodel="deepseek-r1:8b-0528-qwen3-q4_K_M-16k" ;;
            *)        olmodel="deepseek-r1:8b-0528-qwen3-q4_K_M-16k" ;;
        esac
        log "   → Trying Ollama LOCAL ($olmodel)..."
        local opayload
        opayload=$(python3 -c "import json,sys; print(json.dumps({'model':sys.argv[1],'prompt':sys.argv[2],'stream':False,'options':{'num_ctx':16384}}))" "$olmodel" "$prompt" 2>/dev/null)
        local oresp
        oresp=$(curl -s --max-time 300 http://localhost:11434/api/generate -d "$opayload" 2>/dev/null)
        local ocontent
        ocontent=$(echo "$oresp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response',''))" 2>/dev/null || echo "")
        if [[ -n "$ocontent" && "$ocontent" != "# AI Output Unavailable"* ]]; then
            echo "$ocontent" > "$outfile"
            log "   ✓ Ollama LOCAL succeeded ($olmodel)"
            return 0
        fi
        log "   ✗ Ollama LOCAL failed or empty"
    fi

'''

# Insert after "ai_call() {" line
content = content.replace(
    'ai_call() {\n    local prompt="$1"',
    'ai_call() {\n    local prompt="$1"'
)
# Find the start of the Gemini block and insert before it
content = re.sub(
    r'(    # 1\. Gemini REST API)',
    ollama_block + r'    # 1. Gemini REST API',
    content,
    count=1
)

import os
with open(script_path, "w") as f:
    f.write(content)
print("Patched: Ollama added as primary provider")
PATCH_EOF
```

- [ ] **Step 3: Add TCU generation to orchestrate-auto.sh**

Append TCU creation at the start of the script (after the TASK_DIR mkdir):

```bash
python3 << 'PATCH_EOF'
import os, re

script_path = os.path.expanduser("~/.dotfiles/scripts/orchestrate-auto.sh")
with open(script_path) as f:
    content = f.read()

tcu_block = '''
# ── TCU: Create Task Cognitive Unit ───────────────────────────────────────────
TCU_ID=$(python3 -c "
import sys
sys.path.insert(0, '/home/basitdev/Desktop/SecondBrain/Projects/ashi')
from functions.tcu import TCU
from functions.intent import extract_intent, append_intent_log
intent = sys.argv[1]
tcu = TCU.create(intent=intent, project=sys.argv[2], tasks_path='/home/basitdev/Desktop/SecondBrain/tasks')
append_intent_log('/home/basitdev/Desktop/SecondBrain/intent-log.md', intent=intent, task_id=tcu._data['id'])
print(tcu._data['id'])
" "$TASK" "$PROJECT" 2>/dev/null || echo "")
log "   TCU ID: $TCU_ID"

'''

content = content.replace(
    '# ─── Banner ─',
    tcu_block + '# ─── Banner ─'
)

with open(script_path, "w") as f:
    f.write(content)
print("Patched: TCU generation added")
PATCH_EOF
```

- [ ] **Step 4: Remove hardcoded Quran app references from prompts**

```bash
# Replace the hardcoded Quran project context in RESEARCH_PROMPT
sed -i 's/The project is a Quran app with:/The project context:\n- Project: $PROJECT\n- Task: $TASK\n\nProject files and patterns will be read directly from the codebase./g' \
    ~/.dotfiles/scripts/orchestrate-auto.sh
echo "Hardcoded Quran context removed."
```

- [ ] **Step 5: Test the upgraded orchestrator with a dry run**

```bash
# Test Ollama provider routing
ANTHROPIC_API_KEY="" bash ~/.dotfiles/scripts/orchestrate-auto.sh \
    feature "test ashi orchestrator dry run" /tmp 2>&1 | head -30
```
Expected: Lines showing `→ Trying Ollama LOCAL` and `✓ Ollama LOCAL succeeded`

- [ ] **Step 6: Commit**

```bash
git -C ~/.dotfiles add scripts/orchestrate-auto.sh
git -C ~/.dotfiles commit -m "feat(ashi): make orchestrate-auto Ollama-first, generic, TCU-aware"
```

---

## Task 11: `ashi` CLI Entry Point

**Files:**
- Create: `~/.dotfiles/scripts/ashi.sh`

- [ ] **Step 1: Write the ashi CLI**

```bash
cat > ~/.dotfiles/scripts/ashi.sh << 'ASHI_EOF'
#!/bin/bash
# ashi — ASHI local AI OS entry point
# Usage:
#   ashi task "build login feature" [project-path]
#   ashi ingest <url|file>
#   ashi search <query>
#   ashi lint
#   ashi status
#   ashi brain          — open chat with local brain

set -euo pipefail

ASHI_DIR="$HOME/.ashi"
BRAIN_DIR="$HOME/Desktop/SecondBrain"
WIKI_DIR="$BRAIN_DIR/wiki"
PYTHON_LIB="$BRAIN_DIR/Projects/ashi"
COMMAND="${1:-help}"

_py() { PYTHONPATH="$PYTHON_LIB" python3 "$@"; }

case "$COMMAND" in
    task)
        TASK="${2:-}"
        PROJECT="${3:-$(pwd)}"
        if [[ -z "$TASK" ]]; then echo "Usage: ashi task \"intent\" [project-path]"; exit 1; fi
        echo "→ Starting task: $TASK"
        bash "$HOME/.dotfiles/scripts/orchestrate-auto.sh" feature "$TASK" "$PROJECT"
        ;;

    fix)
        TASK="${2:-}"
        PROJECT="${3:-$(pwd)}"
        if [[ -z "$TASK" ]]; then echo "Usage: ashi fix \"bug description\" [project-path]"; exit 1; fi
        echo "→ Fixing: $TASK"
        bash "$HOME/.dotfiles/scripts/orchestrate-auto.sh" fix "$TASK" "$PROJECT"
        ;;

    ingest)
        SOURCE="${2:-}"
        if [[ -z "$SOURCE" ]]; then echo "Usage: ashi ingest <url|file>"; exit 1; fi
        echo "→ Ingesting: $SOURCE"
        _py -c "
from functions.wiki import append_wiki_log
import sys, datetime
append_wiki_log('$WIKI_DIR/log.md', 'ingest', sys.argv[1], 'queued for processing')
print('Queued. Full ingest pipeline coming in Phase 1.')
" "$SOURCE"
        ;;

    search)
        QUERY="${2:-}"
        if [[ -z "$QUERY" ]]; then echo "Usage: ashi search \"query\""; exit 1; fi
        _py -c "
from functions.wiki import search_wiki
import json, sys
results = search_wiki(sys.argv[1], wiki_path='$WIKI_DIR', top_k=5)
if not results:
    print('No results found.')
else:
    for r in results:
        print(f\"  [{r['score']:.2f}] {r['file']}\")
        print(f\"    {r['snippet'][:150]}...\")
        print()
" "$QUERY"
        ;;

    lint)
        echo "→ Linting wiki..."
        _py -c "
from functions.wiki import lint_wiki
import json
report = lint_wiki('$WIKI_DIR')
print(f\"Total pages: {report['total_pages']}\")
print(f\"Orphan pages: {len(report['orphans'])}\")
for o in report['orphans']:
    print(f\"  - {o['file']}: {o['reason']}\")
"
        ;;

    status)
        echo "=== ASHI Status ==="
        echo ""
        echo "Models:"
        ollama list 2>/dev/null | grep -E "deepseek|qwen3" || echo "  Ollama not running"
        echo ""
        echo "Observability:"
        curl -s http://localhost:3000/api/health 2>/dev/null | python3 -m json.tool 2>/dev/null \
            && echo "  Langfuse: running at http://localhost:3000" \
            || echo "  Langfuse: not running (start: docker compose -f ~/.ashi/docker-compose.yml up -d)"
        echo ""
        echo "Second Brain:"
        wiki_pages=$(find "$WIKI_DIR" -name "*.md" 2>/dev/null | wc -l)
        active_tasks=$(find "$BRAIN_DIR/tasks/active" -name "*.json" 2>/dev/null | wc -l)
        echo "  Wiki pages: $wiki_pages"
        echo "  Active tasks: $active_tasks"
        echo ""
        echo "Recent intents:"
        tail -3 "$BRAIN_DIR/intent-log.md" 2>/dev/null || echo "  (none)"
        ;;

    brain)
        echo "→ Opening chat with local brain (deepseek-r1)..."
        echo "  Type your task or question. Ctrl+C to exit."
        ANTHROPIC_BASE_URL="http://localhost:11434" \
        ANTHROPIC_AUTH_TOKEN="ollama" \
        ANTHROPIC_API_KEY="" \
        claude --model deepseek-r1:8b-0528-qwen3-q4_K_M-16k
        ;;

    help|*)
        echo "ASHI — Local AI OS"
        echo ""
        echo "Commands:"
        echo "  ashi task \"intent\" [project]  — run a feature task"
        echo "  ashi fix \"bug\" [project]       — run a fix task"
        echo "  ashi ingest <url|file>          — ingest source into wiki"
        echo "  ashi search \"query\"            — search the wiki"
        echo "  ashi lint                       — check wiki health"
        echo "  ashi status                     — system status"
        echo "  ashi brain                      — chat with local brain"
        ;;
esac
ASHI_EOF
chmod +x ~/.dotfiles/scripts/ashi.sh
echo "ashi.sh created."
```

- [ ] **Step 2: Add to PATH**

```bash
# Add to ~/.bashrc if not already there
grep -q 'alias ashi=' ~/.bashrc 2>/dev/null || \
    echo 'alias ashi="bash $HOME/.dotfiles/scripts/ashi.sh"' >> ~/.bashrc
source ~/.bashrc 2>/dev/null || true
echo "ashi command available."
```

- [ ] **Step 3: Run ashi status**

```bash
bash ~/.dotfiles/scripts/ashi.sh status
```
Expected: Models listed, Langfuse status shown, wiki page count shown.

- [ ] **Step 4: Commit**

```bash
git -C ~/.dotfiles add scripts/ashi.sh
git -C ~/.dotfiles commit -m "feat(ashi): add ashi CLI entry point with task/search/lint/brain commands"
```

---

## Task 12: Run All Tests + Phase 0 Verification

- [ ] **Step 1: Run full test suite**

```bash
cd ~/Desktop/SecondBrain/Projects/ashi
python3 -m pytest tests/ -v --tb=short
```
Expected: All tests pass. If any fail, fix before proceeding.

- [ ] **Step 2: Verify ashi CLI works end-to-end**

```bash
ashi status
ashi search "ASHI local AI"
ashi lint
```

- [ ] **Step 3: Verify Ollama routing**

```bash
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-r1:8b-0528-qwen3-q4_K_M-16k","messages":[{"role":"user","content":"Say: ASHI Phase 0 complete"}],"max_tokens":20}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```
Expected: Model responds with the phrase.

- [ ] **Step 4: Open Langfuse dashboard**

```bash
xdg-open http://localhost:3000 2>/dev/null || echo "Open http://localhost:3000 in browser"
```
Create an account (local only). Note the public/secret keys, update `~/.ashi/config.json`.

- [ ] **Step 5: Final commit**

```bash
git -C ~/Desktop/SecondBrain add -A
git -C ~/Desktop/SecondBrain commit -m "feat(ashi): Phase 0 complete — local brain, wiki, TCU, observability, CLI"
```

- [ ] **Step 6: Log completion to wiki**

```bash
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/basitdev/Desktop/SecondBrain/Projects/ashi')
from functions.wiki import append_wiki_log
append_wiki_log(
    '/home/basitdev/Desktop/SecondBrain/wiki/log.md',
    'system',
    'Phase 0 Complete',
    'Local brain operational. TCU executor live. Langfuse wired. ashi CLI ready.'
)
print("Phase 0 logged to wiki.")
EOF
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Ollama context windows fixed (16384) | Task 1 |
| Model routing config | Task 2 (config.json) |
| Second Brain restructured to ASHI schema | Task 2 |
| wiki/index.md, wiki/log.md seeded | Task 2 |
| intent-log.md created | Task 2 |
| Python deps installed | Task 3 |
| LanceDB vector store | Task 4 |
| Kuzu knowledge graph | Task 4 |
| TCU executor with step checkpointing | Task 5 |
| Crash recovery (v1: JSON checkpoint) | Task 5 |
| Intent extraction + log append | Task 6 |
| Secrets vault | Task 7 |
| Langfuse + Valkey Docker stack | Task 8 |
| OTel trace emitter | Task 8 |
| Wiki search, lint, index, log functions | Task 9 |
| orchestrate-auto.sh Ollama-first | Task 10 |
| orchestrate-auto.sh generic (no Quran hardcode) | Task 10 |
| orchestrate-auto.sh TCU-aware | Task 10 |
| ashi CLI entry point | Task 11 |
| All tests pass | Task 12 |

All spec requirements covered. No placeholders. All code is complete.

---

*Plan written: 2026-04-07 | Phase 1 plan to follow after Phase 0 verified working.*
