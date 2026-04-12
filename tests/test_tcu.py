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
