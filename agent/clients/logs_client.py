"""CloudWatch Logs client: fetch the tail of a Batch job's log stream."""

from __future__ import annotations

import boto3

_logs = boto3.client("logs")


def get_log_tail(log_group: str, log_stream_name: str | None, max_lines: int = 200) -> str:
    if not log_stream_name:
        return ""

    try:
        resp = _logs.get_log_events(
            logGroupName=log_group,
            logStreamName=log_stream_name,
            limit=max_lines,
            startFromHead=False,
        )
    except _logs.exceptions.ResourceNotFoundException:
        return ""

    lines = [event["message"] for event in resp.get("events", [])]
    return "\n".join(lines)
