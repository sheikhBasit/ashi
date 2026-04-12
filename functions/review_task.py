"""
review_task — judge agent. Loads a completed TCU, calls local model, returns scored verdict.
Uses stdlib urllib only — no OpenAI SDK.
"""
import json
import os
import urllib.request
from datetime import datetime

TASKS_PATH = os.path.expanduser("~/Desktop/SecondBrain/tasks")
LOG_PATH = os.path.expanduser("~/Desktop/SecondBrain/AI/agent-logs")
OLLAMA_URL = "http://localhost:11434/api/chat"
JUDGE_MODEL = "qwen3:0.6b"

JUDGE_SYSTEM = """You are a strict quality judge for an AI assistant called ASHI.
Review the completed task and output ONLY valid JSON with no extra text:
{"score": <integer 0-10>, "verdict": "<pass|fail|retry>", "notes": "<one concise sentence>"}

Scoring rules:
- 8-10 → pass (task completed correctly)
- 5-7  → retry (partially done, needs a different approach)
- 0-4  → fail (wrong output, hallucination, or incomplete)"""

JUDGE_USER_TEMPLATE = """Task intent: {intent}
Steps completed: {steps}
Final output summary: {output}"""


def _load_tcu(tcu_id: str, tasks_path: str) -> dict:
    active_path = os.path.join(tasks_path, "active", f"{tcu_id}.json")
    done_path = os.path.join(tasks_path, "done", f"{tcu_id}.json")
    for path in (active_path, done_path):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError(f"TCU not found: {tcu_id}")


def _call_ollama(system: str, user: str, model: str = JUDGE_MODEL) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())
    return result["message"]["content"].strip()


def _parse_verdict(raw: str) -> dict:
    """Extract JSON from model response — handles think tags and markdown fences."""
    # strip <think>...</think>
    import re
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # extract from ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    # find first {...}
    m = re.search(r"\{.*?\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"score": 0, "verdict": "fail", "notes": "judge parse error"}


def _log_verdict(tcu_id: str, verdict: dict) -> None:
    os.makedirs(LOG_PATH, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_PATH, f"{date_str}.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"[{timestamp}] JUDGE tcu={tcu_id} "
        f"score={verdict.get('score')} verdict={verdict.get('verdict')} "
        f"notes={verdict.get('notes')}\n"
    )
    with open(log_file, "a") as f:
        f.write(line)


def review_task(tcu_id: str, tasks_path: str = TASKS_PATH) -> dict:
    """
    Load a TCU, call judge model, return scored verdict.

    Args:
        tcu_id:     TCU identifier string
        tasks_path: Path to tasks directory

    Returns:
        {"score": int, "verdict": "pass"|"fail"|"retry", "notes": str}
    """
    tcu = _load_tcu(tcu_id, tasks_path)

    intent = tcu.get("intent", "unknown")
    raw_steps = tcu.get("steps", [])
    # steps can be a list or a dict keyed by step number
    if isinstance(raw_steps, dict):
        step_list = list(raw_steps.values())
    else:
        step_list = raw_steps
    steps_summary = "; ".join(
        f"{s.get('name','step')}={s.get('status','?')}"
        for s in step_list
        if isinstance(s, dict)
    )
    # last step output or empty
    output = ""
    for step in reversed(step_list):
        if isinstance(step, dict) and step.get("output"):
            output = str(step["output"])[:500]
            break

    user_msg = JUDGE_USER_TEMPLATE.format(
        intent=intent,
        steps=steps_summary or "none",
        output=output or "no output recorded",
    )

    raw = _call_ollama(JUDGE_SYSTEM, user_msg)
    verdict = _parse_verdict(raw)

    # store verdict back in TCU
    tcu["judge"] = verdict
    active_path = os.path.join(tasks_path, "active", f"{tcu_id}.json")
    done_path = os.path.join(tasks_path, "done", f"{tcu_id}.json")
    save_path = done_path if os.path.exists(done_path) else active_path
    if os.path.exists(save_path):
        with open(save_path, "w") as f:
            json.dump(tcu, f, indent=2)

    _log_verdict(tcu_id, verdict)
    return verdict
