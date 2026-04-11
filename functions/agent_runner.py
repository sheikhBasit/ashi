# functions/agent_runner.py
"""
AgentRunner — orchestrates the full HostAgent → TaskAgent loop.
Creates and manages a TCU for the run. Handles budget, safety, convergence.
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

from blackboard import Blackboard
from host_agent import HostAgent
from task_agent import TaskAgent

_TASKS_PATH = os.path.expanduser("~/Desktop/SecondBrain/tasks")

try:
    from tcu import TCU
    _TCU_AVAILABLE = True
except ImportError:
    _TCU_AVAILABLE = False


@dataclass
class AgentResult:
    goal: str
    status: str  # "done" | "failed" | "awaiting_confirmation" | "budget_exceeded"
    steps_completed: int
    steps_total: int
    outputs: list[dict] = field(default_factory=list)
    final_output: str = ""
    tcu_id: Optional[str] = None
    pending_confirmation: Optional[dict] = None
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None


def run_agent(
    goal: str,
    max_steps: int = 10,
    require_confirmation: bool = True,
    max_consecutive_failures: int = 3,
    tasks_path: str = _TASKS_PATH,
    project: str = "ashi",
) -> AgentResult:
    """
    Run the full agent loop for a goal.

    Args:
        goal: What to accomplish
        max_steps: Hard cap on total steps
        require_confirmation: Whether to pause on irreversible actions
        max_consecutive_failures: Stop if this many steps fail in a row
        tasks_path: Where to write TCU files
        project: TCU project label

    Returns:
        AgentResult with full run state
    """
    bb = Blackboard(goal=goal, max_steps=max_steps)
    tcu = None
    tcu_id = None

    if _TCU_AVAILABLE:
        try:
            tcu = TCU.create(goal, project, tasks_path)
            tcu_id = tcu._data["id"]
        except Exception:
            pass

    host = HostAgent()
    task = TaskAgent(require_confirmation=require_confirmation)

    # Phase 1: planning
    try:
        steps = host.plan(bb)
        # Ensure bb.plan is populated even when host.plan is mocked
        if not bb.plan:
            bb.set_plan(steps)
    except Exception as e:
        return AgentResult(
            goal=goal,
            status="failed",
            steps_completed=0,
            steps_total=0,
            error=f"Planning failed: {e}",
            tcu_id=tcu_id,
            finished_at=datetime.now().isoformat(),
        )

    if tcu:
        try:
            tcu.start_step(0, f"Planning: {goal[:60]}")
            tcu.complete_step(0, f"{len(steps)} steps planned")
        except Exception:
            pass

    # Phase 2: execution loop
    outputs = []
    consecutive_failures = 0

    for i, step in enumerate(bb.plan):
        if not bb.has_budget:
            return AgentResult(
                goal=goal,
                status="budget_exceeded",
                steps_completed=i,
                steps_total=bb.total_steps,
                outputs=outputs,
                tcu_id=tcu_id,
                finished_at=datetime.now().isoformat(),
            )

        if tcu:
            try:
                tcu.start_step(i + 1, step[:80])
            except Exception:
                pass

        step_result = task.execute_step(bb, i)
        outputs.append({"step": step, **step_result})

        if step_result.get("requires_confirmation"):
            return AgentResult(
                goal=goal,
                status="awaiting_confirmation",
                steps_completed=i,
                steps_total=bb.total_steps,
                outputs=outputs,
                pending_confirmation={
                    "step_index": i,
                    "step": step,
                    "pending_call": step_result.get("pending_call"),
                },
                tcu_id=tcu_id,
                finished_at=datetime.now().isoformat(),
            )

        if step_result["success"]:
            consecutive_failures = 0
            bb.record_result(i, step_result.get("output", ""), success=True)
            if tcu:
                try:
                    tcu.complete_step(i + 1, step_result.get("output", "")[:200])
                except Exception:
                    pass
        else:
            consecutive_failures += 1
            bb.record_result(i, step_result.get("error", "unknown error"), success=False)
            if tcu:
                try:
                    tcu.complete_step(i + 1, f"FAILED: {step_result.get('error', '')[:200]}")
                except Exception:
                    pass
            if consecutive_failures >= max_consecutive_failures:
                return AgentResult(
                    goal=goal,
                    status="failed",
                    steps_completed=i + 1,
                    steps_total=bb.total_steps,
                    outputs=outputs,
                    error=f"Stopped after {consecutive_failures} consecutive failures",
                    tcu_id=tcu_id,
                    finished_at=datetime.now().isoformat(),
                )

    successful = [o for o in outputs if o.get("success")]
    final_output = bb.context_summary()

    if tcu:
        try:
            tcu.mark_done(judge_score=len(successful) / max(len(outputs), 1))
        except Exception:
            pass

    return AgentResult(
        goal=goal,
        status="done",
        steps_completed=len(outputs),
        steps_total=bb.total_steps,
        outputs=outputs,
        final_output=final_output,
        tcu_id=tcu_id,
        finished_at=datetime.now().isoformat(),
    )
