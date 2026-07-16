import pytest

from agent.clients import llm_client
from agent.models import JobContext


def _job():
    return JobContext(
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


class _FakeToolUseBlock:
    def __init__(self, input_):
        self.type = "tool_use"
        self.name = "submit_decision"
        self.input = input_


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _fake_client(response, monkeypatch):
    class _FakeMessages:
        def create(self, **kwargs):
            assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_decision"}
            assert kwargs["tools"][0]["name"] == "submit_decision"
            return response

    class _FakeClient:
        def __init__(self, api_key):
            self.messages = _FakeMessages()

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _FakeClient)


def test_analyze_parses_tool_use_into_decision(monkeypatch):
    fake_input = {
        "action": "reroute",
        "root_cause": "bad data",
        "confidence": 0.8,
        "explanation": "the input is malformed",
        "reroute_reason": "missing field",
    }
    _fake_client(_FakeResponse([_FakeToolUseBlock(fake_input)]), monkeypatch)

    decision = llm_client.analyze(_job(), "log", [], "f.py", "content", api_key="x")

    assert decision.action.value == "reroute"
    assert decision.reroute_reason == "missing field"
    assert decision.confidence == 0.8


def test_analyze_raises_without_tool_use_block(monkeypatch):
    _fake_client(_FakeResponse([]), monkeypatch)

    with pytest.raises(RuntimeError):
        llm_client.analyze(_job(), "log", [], "f.py", "content", api_key="x")
