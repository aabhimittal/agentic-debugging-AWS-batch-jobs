"""Lambda entrypoint: triggered by SQS messages on the Dead Letter Queue.
Runs the specialized recovery script for each rerouted job."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.recovery import recovery_script

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    results = []
    for record in event.get("Records", []):
        message = json.loads(record["body"])
        logger.info("Running recovery for job %s", message.get("job_id"))
        result = recovery_script.run(message)
        logger.info("Recovery result for job %s: %s", message.get("job_id"), result.to_dict())
        results.append({"job_id": message.get("job_id"), **result.to_dict()})
    return {"results": results}
