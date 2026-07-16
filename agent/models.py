"""Shared data models passed between the analyzer, LLM client, and recovery path."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentAction(StrEnum):
    FIX = "fix"
    REROUTE = "reroute"


@dataclass
class Commit:
    sha: str
    message: str
    author: str
    date: str
    files_changed: list[str] = field(default_factory=list)
    diff: str = ""

    def to_prompt_block(self) -> str:
        files = ", ".join(self.files_changed) or "(no file list)"
        diff = self.diff.strip() or "(diff omitted)"
        return (
            f"commit {self.sha[:12]} by {self.author} on {self.date}\n"
            f"    {self.message.strip()}\n"
            f"    files: {files}\n"
            f"    diff:\n{diff}"
        )


@dataclass
class JobContext:
    job_id: str
    job_name: str
    job_definition: str
    job_queue: str
    status: str
    status_reason: str | None
    exit_code: int | None
    log_group: str
    log_stream_name: str | None
    container_image: str | None
    parameters: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def source_repo(self) -> str | None:
        return self.tags.get("agentic-debug:repo") or self.parameters.get("sourceRepo")

    @property
    def entrypoint(self) -> str | None:
        return self.tags.get("agentic-debug:entrypoint") or self.parameters.get("entrypoint")

    @property
    def ref(self) -> str:
        return self.tags.get("agentic-debug:ref") or self.parameters.get("ref") or "main"


@dataclass
class AgentDecision:
    action: AgentAction
    root_cause: str
    confidence: float
    explanation: str
    suggested_fix: str | None = None
    fix_file_path: str | None = None
    reroute_reason: str | None = None

    @staticmethod
    def from_tool_input(payload: dict[str, Any]) -> AgentDecision:
        return AgentDecision(
            action=AgentAction(payload["action"]),
            root_cause=payload["root_cause"],
            confidence=float(payload.get("confidence", 0.0)),
            explanation=payload["explanation"],
            suggested_fix=payload.get("suggested_fix"),
            fix_file_path=payload.get("fix_file_path"),
            reroute_reason=payload.get("reroute_reason"),
        )
