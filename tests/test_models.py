from agent.models import AgentAction, AgentDecision, Commit, JobContext


def _job(**overrides):
    defaults = dict(
        job_id="1",
        job_name="n",
        job_definition="d",
        job_queue="q",
        status="FAILED",
        status_reason=None,
        exit_code=1,
        log_group="lg",
        log_stream_name="ls",
        container_image="img",
    )
    defaults.update(overrides)
    return JobContext(**defaults)


def test_commit_to_prompt_block_includes_message_and_files():
    commit = Commit(
        sha="abc123def456789",
        message="Fix bug",
        author="alice",
        date="2024-01-01T00:00:00Z",
        files_changed=["a.py", "b.py"],
        diff="+ x = 1",
    )
    block = commit.to_prompt_block()
    assert "abc123def456" in block
    assert "Fix bug" in block
    assert "a.py, b.py" in block
    assert "+ x = 1" in block


def test_job_context_prefers_tags_over_parameters():
    job = _job(
        parameters={"sourceRepo": "param/repo", "entrypoint": "param.py", "ref": "param-ref"},
        tags={
            "agentic-debug:repo": "tag/repo",
            "agentic-debug:entrypoint": "tag.py",
            "agentic-debug:ref": "tag-ref",
        },
    )
    assert job.source_repo == "tag/repo"
    assert job.entrypoint == "tag.py"
    assert job.ref == "tag-ref"


def test_job_context_falls_back_to_parameters_then_default_ref():
    job = _job(parameters={"sourceRepo": "param/repo", "entrypoint": "param.py"})
    assert job.source_repo == "param/repo"
    assert job.entrypoint == "param.py"
    assert job.ref == "main"


def test_job_context_has_no_source_when_unconfigured():
    job = _job()
    assert job.source_repo is None
    assert job.entrypoint is None


def test_agent_decision_from_tool_input():
    payload = {
        "action": "fix",
        "root_cause": "x",
        "confidence": 0.9,
        "explanation": "y",
        "suggested_fix": "code",
        "fix_file_path": "a.py",
    }
    decision = AgentDecision.from_tool_input(payload)
    assert decision.action == AgentAction.FIX
    assert decision.confidence == 0.9
    assert decision.suggested_fix == "code"
