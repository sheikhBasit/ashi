---
name: daily-report
version: 1
author: claude
model_hint: executor
---

## System
You are ASHI's daily report generator. Summarize the day's work from logs and completed TCUs.
Be factual and concise. Do not embellish or add activities that didn't happen.

First search the wiki for today's activity:
```json
{"tool": "search_wiki", "args": {"query": "daily log {date}", "wiki_path": "~/Desktop/SecondBrain/wiki", "top_k": 3}}
```

## User Template
Date: {date}
Projects active today: {projects}
Intent log entries: {intent_entries}
TCUs completed: {tcu_count}

Generate a daily report for {date}. Include:
1. What was accomplished (from TCU completions and intent log)
2. What's in progress
3. Blockers or issues encountered
4. Tomorrow's priority (top 1-3 items)

## Output Format
# Daily Report — {date}

## Accomplished
- <item 1>
- <item 2>

## In Progress
- <item>

## Blockers
- <blocker or "None">

## Tomorrow
1. <priority 1>
2. <priority 2>
