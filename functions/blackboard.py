# functions/blackboard.py
"""
Blackboard — shared state for one agent run.
All agents read/write through this object. Serializable to dict for TCU storage.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Blackboard:
    goal: str
    max_steps: int = 20
    plan: list[str] = field(default_factory=list)
    results: dict[int, dict] = field(default_factory=dict)
    current_step_index: int = 0
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    final_output: Optional[str] = None

    def set_plan(self, steps: list[str]) -> None:
        self.plan = steps
        self.current_step_index = 0

    @property
    def total_steps(self) -> int:
        return len(self.plan)

    @property
    def steps_remaining(self) -> int:
        completed = len(self.results)
        return self.max_steps - completed

    @property
    def is_done(self) -> bool:
        if not self.plan:
            return False
        return len(self.results) >= len(self.plan)

    @property
    def has_budget(self) -> bool:
        return self.steps_remaining > 0

    def record_result(self, step_index: int, output: str, success: bool) -> None:
        self.results[step_index] = {
            "step": self.plan[step_index] if step_index < len(self.plan) else "unknown",
            "output": output,
            "success": success,
            "recorded_at": datetime.now().isoformat(),
        }
        self.current_step_index = step_index + 1

    def context_summary(self) -> str:
        """Compact summary of completed work for injection into next prompt."""
        if not self.results:
            return "No steps completed yet."
        lines = [f"Goal: {self.goal}", "Completed steps:"]
        for i, r in sorted(self.results.items()):
            status = "✓" if r["success"] else "✗"
            out = r["output"][:200] + "..." if len(r["output"]) > 200 else r["output"]
            lines.append(f"  {status} Step {i+1}: {r['step']}\n     → {out}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "max_steps": self.max_steps,
            "plan": self.plan,
            "results": {str(k): v for k, v in self.results.items()},
            "current_step_index": self.current_step_index,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "final_output": self.final_output,
        }
