"""SQS client: reroute a failed job's context to the Dead Letter Queue."""

from __future__ import annotations

import json
import os

import boto3

from agent.models import AgentDecision, JobContext

_sqs = boto3.client("sqs")


def send_to_dlq(job: JobContext, decision: AgentDecision, queue_url: str | None = None) -> str:
    queue_url = queue_url or os.environ["DLQ_URL"]
    message = {
        "job_id": job.job_id,
        "job_name": job.job_name,
        "job_definition": job.job_definition,
        "job_queue": job.job_queue,
        "parameters": job.parameters,
        "tags": job.tags,
        "status_reason": job.status_reason,
        "root_cause": decision.root_cause,
        "reroute_reason": decision.reroute_reason,
    }
    resp = _sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
    return resp["MessageId"]
