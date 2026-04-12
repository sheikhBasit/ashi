---
name: opencode-task
description: Run a coding task using OpenCode with local Ollama (qwen2.5-coder:14b). Zero API cost. For multi-file edits, refactors, and project-aware coding tasks.
model: qwen2.5-coder:14b
tags: [coding, local, zero-cost]
---

# OpenCode Task

You are routing this task to OpenCode — a terminal coding agent running locally via Ollama.

## When to use
- Multi-file edits across a project
- Refactoring existing code
- Writing tests for existing functions
- Any coding task where cost matters

## How it runs
OpenCode is called as a subprocess:
```bash
opencode run --model ollama/qwen2.5-coder:14b "{task}"
```

## Task
{task}

## Project directory
{cwd}

## Context
{context}
