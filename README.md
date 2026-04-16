# ASHI — Personal AI OS

> Local-first AI operating system. Always-on desktop app with voice interface, agent loop, memory, and live system monitoring.

Built with Tauri (desktop), React + TypeScript (UI), and a Python backend. Runs fully offline via Ollama — no cloud required.

---

## What It Does

ASHI watches your system, listens for commands, and acts as an always-on AI layer on your machine.

- **Voice interface** — wake word activation, Whisper STT, Piper TTS (deep male voice)
- **Agent loop** — describes tasks in natural language, agents plan and execute
- **Memory** — vector memory (LanceDB) + knowledge graph (Kuzu) + SQLite task store
- **Live monitoring** — CPU, RAM, disk, processes, services in real time
- **115 skills** — Ollama-powered skill library covering dev, research, life management
- **Vizier mode** — advisory agent that reads context and provides unprompted insights
- **Terminal** — sandboxed shell access via Tauri IPC

---

## Stack

| Layer | Tech |
|-------|------|
| Desktop | Tauri (Rust) |
| Frontend | Vite + React + TypeScript + Tailwind |
| Backend | Python 3.11, FastAPI |
| AI | Ollama (local) · Claude API · LangChain |
| Memory | LanceDB (vector) · Kuzu (graph) · SQLite |
| Voice | Whisper STT · Piper TTS |
| Tracing | Langfuse |

---

## Panels

- **Pipeline** — agent task queue and execution status
- **Wiki** — personal knowledge base with vector search
- **Tasks** — TCU (task/context unit) management
- **Terminal** — sandboxed shell
- **Monitor** — live system metrics (CPU/RAM/disk/processes)
- **Logs** — structured agent and skill logs

---

## Quick Start

```bash
git clone https://github.com/sheikhBasit/ashi
cd ashi

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add API keys

# Desktop app
cd app
npm install
npm run tauri dev
```

**Requirements:** Ollama running locally (`ollama serve`), Python 3.11+, Node.js 20+, Rust toolchain

---

## Project Structure

```
ashi/
├── app/                    — Tauri desktop app
│   ├── src/                — React + TypeScript panels
│   └── src-tauri/          — Rust Tauri commands
├── functions/              — Python backend
│   ├── ashi_daemon.py      — Main daemon process
│   ├── agent_runner.py     — Agent execution loop
│   ├── memory_manager.py   — LanceDB + Kuzu memory
│   ├── monitor.py          — System metrics collector
│   └── context_engine.py   — Context assembly for agents
├── skills/                 — Ollama skill prompts (115 skills)
├── scripts/                — Setup and utility scripts
└── tests/                  — Playwright + pytest test suite
```

---

Built by [Abdul Basit](https://github.com/sheikhBasit) · Python · Rust · TypeScript · Tauri · LangChain · Ollama
