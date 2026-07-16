"""Lambda entrypoint: triggered by an EventBridge rule on Batch job FAILED
state changes. Diagnoses the failure with an LLM agent and either opens a
GitHub PR with a fix, or reroutes the job to the Dead Letter Queue.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.clients import (
    batch_client,
    github_client,
    llm_client,
    logs_client,
    notify_client,
    secrets_client,
    sqs_client,
)
from agent.models import AgentAction, AgentDecision, JobContext

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _resolve_source(job: JobContext) -> tuple[str | None, str | None, str]:
    repo = job.source_repo or os.environ.get("DEFAULT_GITHUB_REPO")
    entrypoint = job.entrypoint or os.environ.get("DEFAULT_ENTRYPOINT")
    ref = job.ref or os.environ.get("DEFAULT_REF", "main")
    return repo, entrypoint, ref


def _diagnose(job: JobContext) -> tuple[AgentDecision, str | None, str | None, str, str]:
    log_tail = logs_client.get_log_tail(job.log_group, job.log_stream_name)
    repo, entrypoint, ref = _resolve_source(job)

    github_token = secrets_client.get_secret(os.environ["GITHUB_TOKEN_SECRET_ID"])
    anthropic_key = secrets_client.get_secret(os.environ["ANTHROPIC_API_KEY_SECRET_ID"])

    commits = []
    file_content = None
    if repo:
        commits = github_client.get_last_successful_commits(
            repo, github_token, ref=ref, path=entrypoint, count=10
        )
        if entrypoint:
            file_content = github_client.get_file_content(repo, entrypoint, ref, github_token)

    decision = llm_client.analyze(job, log_tail, commits, entrypoint, file_content, api_key=anthropic_key)

    # Guardrail: never act on "fix" without everything needed to open a real PR.
    has_fix_context = repo and entrypoint and decision.suggested_fix and decision.fix_file_path
    if decision.action == AgentAction.FIX and not has_fix_context:
        logger.warning("Model chose 'fix' but source repo/file context is incomplete; downgrading to reroute")
        decision = AgentDecision(
            action=AgentAction.REROUTE,
            root_cause=decision.root_cause,
            confidence=decision.confidence,
            explanation=decision.explanation,
            reroute_reason="Agent lacked enough repo context to safely apply an automated fix.",
        )

    return decision, repo, entrypoint, ref, github_token


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    detail = event["detail"]
    job_id = detail["jobId"]
    logger.info("Analyzing failed Batch job %s", job_id)

    job = batch_client.describe_job(job_id)
    decision, repo, entrypoint, ref, github_token = _diagnose(job)

    result: dict[str, Any] = {
        "job_id": job.job_id,
        "action": decision.action.value,
        "root_cause": decision.root_cause,
        "confidence": decision.confidence,
    }

    if decision.action == AgentAction.FIX:
        pr_url = github_client.create_fix_pr(
            repo=repo,
            base_ref=ref,
            file_path=decision.fix_file_path,
            new_content=decision.suggested_fix,
            root_cause=decision.root_cause,
            explanation=decision.explanation,
            job_id=job.job_id,
            token=github_token,
        )
        result["pull_request_url"] = pr_url
        notify_client.publish(
            subject=f"[agentic-debug] Fix proposed for job {job.job_name}",
            message=(
                f"Job {job.job_id} ({job.job_name}) failed.\n\n"
                f"Root cause: {decision.root_cause}\n\n"
                f"{decision.explanation}\n\n"
                f"Fix PR opened: {pr_url}"
            ),
        )
    else:
        message_id = sqs_client.send_to_dlq(job, decision)
        result["dlq_message_id"] = message_id
        notify_client.publish(
            subject=f"[agentic-debug] Job {job.job_name} rerouted to DLQ",
            message=(
                f"Job {job.job_id} ({job.job_name}) failed and was rerouted to the "
                f"dead letter queue for recovery.\n\n"
                f"Root cause: {decision.root_cause}\n\n"
                f"Reroute reason: {decision.reroute_reason}\n\n"
                f"{decision.explanation}"
            ),
        )

    logger.info("Decision for job %s: %s", job_id, result)
    return result
