import json
from pathlib import Path
from unittest.mock import MagicMock

from agent import analyzer_handler
from agent.models import AgentAction, AgentDecision, JobContext

FIXTURE = Path(__file__).parent / "fixtures" / "batch_failed_event.json"


def _job(**tag_overrides):
    tags = {
        "agentic-debug:repo": "o/r",
        "agentic-debug:entrypoint": "demo/process_orders.py",
        "agentic-debug:ref": "main",
    }
    tags.update(tag_overrides)
    return JobContext(
        job_id="job-1",
        job_name="demo",
        job_definition="def",
        job_queue="q",
        status="FAILED",
        status_reason="boom",
        exit_code=1,
        log_group="/aws/batch/job",
        log_stream_name="stream",
        container_image="img",
        tags=tags,
    )


def _patch_common(monkeypatch, job, decision):
    monkeypatch.setattr(analyzer_handler.batch_client, "describe_job", lambda job_id: job)
    monkeypatch.setattr(analyzer_handler.logs_client, "get_log_tail", lambda *a, **k: "log")
    monkeypatch.setattr(analyzer_handler.secrets_client, "get_secret", lambda sid: "secret")
    monkeypatch.setattr(analyzer_handler.github_client, "get_last_successful_commits", lambda *a, **k: [])
    monkeypatch.setattr(analyzer_handler.github_client, "get_file_content", lambda *a, **k: "old code")
    monkeypatch.setattr(analyzer_handler.llm_client, "analyze", lambda *a, **k: decision)


def test_fixture_event_has_expected_job_id():
    event = json.loads(FIXTURE.read_text())
    assert event["detail"]["jobId"] == "job-1"
    assert event["detail"]["status"] == "FAILED"


def test_handler_opens_pr_on_fix_decision(monkeypatch):
    decision = AgentDecision(
        action=AgentAction.FIX,
        root_cause="missing discount_pct default",
        confidence=0.9,
        explanation="a recent commit dropped the .get() fallback",
        suggested_fix="new code",
        fix_file_path="demo/process_orders.py",
    )
    _patch_common(monkeypatch, _job(), decision)

    create_fix_pr_mock = MagicMock(return_value="https://github.com/o/r/pull/1")
    monkeypatch.setattr(analyzer_handler.github_client, "create_fix_pr", create_fix_pr_mock)
    publish_mock = MagicMock()
    monkeypatch.setattr(analyzer_handler.notify_client, "publish", publish_mock)
    send_to_dlq_mock = MagicMock()
    monkeypatch.setattr(analyzer_handler.sqs_client, "send_to_dlq", send_to_dlq_mock)

    event = json.loads(FIXTURE.read_text())
    result = analyzer_handler.handler(event, None)

    assert result["action"] == "fix"
    assert result["pull_request_url"] == "https://github.com/o/r/pull/1"
    create_fix_pr_mock.assert_called_once()
    publish_mock.assert_called_once()
    send_to_dlq_mock.assert_not_called()


def test_handler_reroutes_to_dlq_on_reroute_decision(monkeypatch):
    decision = AgentDecision(
        action=AgentAction.REROUTE,
        root_cause="malformed order record",
        confidence=0.7,
        explanation="an eu-region record is missing discount_pct entirely",
        reroute_reason="validate and drop/clean records missing discount_pct",
    )
    _patch_common(monkeypatch, _job(), decision)

    send_to_dlq_mock = MagicMock(return_value="msg-1")
    monkeypatch.setattr(analyzer_handler.sqs_client, "send_to_dlq", send_to_dlq_mock)
    publish_mock = MagicMock()
    monkeypatch.setattr(analyzer_handler.notify_client, "publish", publish_mock)
    create_fix_pr_mock = MagicMock()
    monkeypatch.setattr(analyzer_handler.github_client, "create_fix_pr", create_fix_pr_mock)

    result = analyzer_handler.handler({"detail": {"jobId": "job-1"}}, None)

    assert result["action"] == "reroute"
    assert result["dlq_message_id"] == "msg-1"
    send_to_dlq_mock.assert_called_once()
    create_fix_pr_mock.assert_not_called()


def test_handler_downgrades_fix_to_reroute_without_repo_context(monkeypatch):
    job = _job()
    job.tags = {}  # no source repo configured, and no DEFAULT_GITHUB_REPO env var in tests
    decision = AgentDecision(
        action=AgentAction.FIX,
        root_cause="bug",
        confidence=0.9,
        explanation="exp",
        suggested_fix="new code",
        fix_file_path="x.py",
    )
    _patch_common(monkeypatch, job, decision)

    send_to_dlq_mock = MagicMock(return_value="msg-2")
    monkeypatch.setattr(analyzer_handler.sqs_client, "send_to_dlq", send_to_dlq_mock)
    monkeypatch.setattr(analyzer_handler.notify_client, "publish", MagicMock())
    create_fix_pr_mock = MagicMock()
    monkeypatch.setattr(analyzer_handler.github_client, "create_fix_pr", create_fix_pr_mock)

    result = analyzer_handler.handler({"detail": {"jobId": "job-1"}}, None)

    assert result["action"] == "reroute"
    create_fix_pr_mock.assert_not_called()
    send_to_dlq_mock.assert_called_once()
