"""Specialized recovery logic for jobs the agent rerouted to the DLQ.

This is deliberately simple/generic: it validates the job's input payload
against a minimal schema, quarantines anything that doesn't pass, and
(optionally, opt-in via AUTO_RESUBMIT) resubmits the job with the cleaned
input. In a real pipeline this module is where you'd encode
domain-specific repair rules for your data.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3

from agent.clients import batch_client, notify_client

_s3 = boto3.client("s3")

REQUIRED_ORDER_FIELDS = {"order_id", "amount", "quantity"}


class RecoveryResult:
    def __init__(self, status: str, detail: str, resubmitted_job_id: str | None = None):
        self.status = status  # "quarantined" | "resubmitted" | "skipped"
        self.detail = detail
        self.resubmitted_job_id = resubmitted_job_id

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "detail": self.detail, "resubmitted_job_id": self.resubmitted_job_id}


def _clean_orders(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split records into (clean, dropped), coercing minor issues where safe."""
    clean: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for record in records:
        if not REQUIRED_ORDER_FIELDS.issubset(record.keys()):
            dropped.append(record)
            continue
        try:
            amount = float(str(record["amount"]).replace("$", "").strip())
            quantity = int(record["quantity"])
        except (TypeError, ValueError):
            dropped.append(record)
            continue
        cleaned = dict(record)
        cleaned["amount"] = amount
        cleaned["quantity"] = quantity
        cleaned.setdefault("discount_pct", 0)
        clean.append(cleaned)

    return clean, dropped


def _quarantine_bucket() -> str | None:
    return os.environ.get("QUARANTINE_BUCKET")


def run(message: dict[str, Any]) -> RecoveryResult:
    job_id = message.get("job_id", "unknown")
    parameters = message.get("parameters", {}) or {}
    input_uri = parameters.get("inputUri")

    if not input_uri or not input_uri.startswith("s3://"):
        return RecoveryResult("skipped", f"No recoverable S3 input for job {job_id}; manual review required.")

    bucket, key = input_uri[5:].split("/", 1)
    obj = _s3.get_object(Bucket=bucket, Key=key)
    records = json.loads(obj["Body"].read())

    clean, dropped = _clean_orders(records if isinstance(records, list) else [records])

    timestamp = message.get("_recovered_at") or datetime.now(UTC).isoformat()
    quarantine_bucket = _quarantine_bucket()
    if dropped and quarantine_bucket:
        quarantine_body = {
            "job_id": job_id,
            "root_cause": message.get("root_cause"),
            "dropped_records": dropped,
        }
        _s3.put_object(
            Bucket=quarantine_bucket,
            Key=f"quarantine/{job_id}/{timestamp}.json",
            Body=json.dumps(quarantine_body).encode("utf-8"),
        )

    if not clean:
        notify_client.publish(
            subject=f"[agentic-debug] Recovery could not salvage job {job_id}",
            message=f"All {len(dropped)} record(s) failed validation and were quarantined. "
            "No resubmission attempted.",
        )
        return RecoveryResult("quarantined", f"All {len(dropped)} records quarantined; nothing left to resubmit.")

    if os.environ.get("AUTO_RESUBMIT", "false").lower() != "true":
        return RecoveryResult(
            "quarantined",
            f"{len(clean)} record(s) cleaned, {len(dropped)} quarantined. "
            "AUTO_RESUBMIT is disabled, so no new job was submitted.",
        )

    clean_key = f"recovered/{job_id}/{timestamp}.json"
    _s3.put_object(Bucket=bucket, Key=clean_key, Body=json.dumps(clean).encode("utf-8"))

    new_job_id = batch_client.resubmit_job(
        job_name=f"recovered-{message.get('job_name', job_id)}"[:128],
        job_queue=message["job_queue"],
        job_definition=message["job_definition"],
        parameters={**parameters, "inputUri": f"s3://{bucket}/{clean_key}"},
        tags={**message.get("tags", {}), "agentic-debug:recovered-from": job_id},
    )

    notify_client.publish(
        subject=f"[agentic-debug] Recovered and resubmitted job {job_id}",
        message=(
            f"{len(clean)} record(s) cleaned, {len(dropped)} quarantined.\n"
            f"Resubmitted as new job {new_job_id}."
        ),
    )
    return RecoveryResult(
        "resubmitted", f"Resubmitted with {len(clean)} cleaned record(s).", resubmitted_job_id=new_job_id
    )
