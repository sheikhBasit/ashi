"""
Task Cognitive Unit — the atomic unit of work in ASHI.
A TCU is simultaneously: intent, plan, execution log, and judge review.
Checkpointed to disk after every step for crash recovery (v1 implementation).
"""
import json
import os
from datetime import datetime
from enum import Enum
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
        active_dir = os.path.join(tasks_path, "active")
        os.makedirs(active_dir, exist_ok=True)
        path = os.path.join(active_dir, f"{task_id}.json")
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
        lines = [f"## Intent\n{self.intent}\n", "## Execution Log"]
        for step_num, step in sorted(
            self._data["steps"].items(), key=lambda x: int(x[0])
        ):
            icon = "done" if step["status"] == "done" else "->"
            lines.append(f"- [{icon}] Step {step_num}: {step['name']}")
            if step.get("output"):
                lines.append(f"  Output: {step['output'][:200]}")
        if self.judge_score:
            lines.append(f"\n## Judge Review\nScore: {self.judge_score}")
        return "\n".join(lines)
