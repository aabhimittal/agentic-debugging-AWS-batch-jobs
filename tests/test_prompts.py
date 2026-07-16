from agent.models import JobContext
from agent.prompts import build_user_prompt


def _job():
    return JobContext(
        job_id="job-1",
        job_name="demo",
        job_definition="def",
        job_queue="q",
        status="FAILED",
        status_reason="Essential container in task exited",
        exit_code=1,
        log_group="lg",
        log_stream_name="ls",
        container_image="img",
    )


def test_build_user_prompt_includes_job_logs_and_file():
    prompt = build_user_prompt(_job(), "KeyError: 'discount_pct'", [], "demo/process_orders.py", "print('hi')")
    assert "job-1" in prompt
    assert "KeyError" in prompt
    assert "demo/process_orders.py" in prompt
    assert "print('hi')" in prompt


def test_build_user_prompt_handles_missing_file():
    prompt = build_user_prompt(_job(), "some log", [], None, None)
    assert "you cannot propose a code fix" in prompt
