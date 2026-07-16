"""Anthropic (Claude) client: the actual diagnosis step of the agent."""

from __future__ import annotations

import os

import anthropic

from agent.models import AgentDecision, Commit, JobContext
from agent.prompts import SYSTEM_PROMPT, build_user_prompt

DEFAULT_MODEL = "claude-sonnet-5"

DECISION_TOOL = {
    "name": "submit_decision",
    "description": (
        "Submit the agent's diagnosis and chosen remediation action for the "
        "failed AWS Batch job."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["fix", "reroute"],
                "description": "'fix' to propose a code patch, 'reroute' to send to the DLQ.",
            },
            "root_cause": {
                "type": "string",
                "description": "Concise statement of what actually caused the failure.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence in the root_cause and chosen action, 0-1.",
            },
            "explanation": {
                "type": "string",
                "description": "Reasoning that connects the logs/commits to the root cause.",
            },
            "suggested_fix": {
                "type": "string",
                "description": (
                    "Required when action='fix'. The COMPLETE corrected contents of "
                    "fix_file_path, not a diff."
                ),
            },
            "fix_file_path": {
                "type": "string",
                "description": "Required when action='fix'. Repo-relative path of the file to patch.",
            },
            "reroute_reason": {
                "type": "string",
                "description": (
                    "Required when action='reroute'. What a recovery script should check "
                    "for or clean up in the input data."
                ),
            },
        },
        "required": ["action", "root_cause", "confidence", "explanation"],
    },
}


def analyze(
    job: JobContext,
    log_tail: str,
    commits: list[Commit],
    file_path: str | None,
    file_content: str | None,
    api_key: str | None = None,
    model: str | None = None,
) -> AgentDecision:
    client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
    user_prompt = build_user_prompt(job, log_tail, commits, file_path, file_content)

    response = client.messages.create(
        model=model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "submit_decision"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_decision":
            return AgentDecision.from_tool_input(block.input)

    raise RuntimeError("Model response did not include a submit_decision tool call")
