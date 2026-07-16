"""AWS Batch client: fetch job details and (for recovery) resubmit jobs."""

from __future__ import annotations

import boto3

from agent.models import JobContext

_batch = boto3.client("batch")


def describe_job(job_id: str) -> JobContext:
    resp = _batch.describe_jobs(jobs=[job_id])
    jobs = resp.get("jobs", [])
    if not jobs:
        raise ValueError(f"Batch job {job_id} not found")
    job = jobs[0]

    container = job.get("container", {}) or {}
    log_stream_name = container.get("logStreamName")
    parameters = {k: str(v) for k, v in (job.get("parameters") or {}).items()}
    tags = {k: str(v) for k, v in (job.get("tags") or {}).items()}

    return JobContext(
        job_id=job["jobId"],
        job_name=job["jobName"],
        job_definition=job.get("jobDefinition", ""),
        job_queue=job.get("jobQueue", ""),
        status=job.get("status", "UNKNOWN"),
        status_reason=job.get("statusReason"),
        exit_code=container.get("exitCode"),
        log_group="/aws/batch/job",
        log_stream_name=log_stream_name,
        container_image=container.get("image"),
        parameters=parameters,
        tags=tags,
    )


def resubmit_job(
    job_name: str,
    job_queue: str,
    job_definition: str,
    parameters: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    """Resubmit a job (used by the recovery path after cleaning its input)."""
    resp = _batch.submit_job(
        jobName=job_name,
        jobQueue=job_queue,
        jobDefinition=job_definition,
        parameters=parameters or {},
        tags=tags or {},
    )
    return resp["jobId"]
