"""SNS client: notify humans of the agent's decision."""

from __future__ import annotations

import os

import boto3

_sns = boto3.client("sns")


def publish(subject: str, message: str, topic_arn: str | None = None) -> None:
    topic_arn = topic_arn or os.environ["SNS_TOPIC_ARN"]
    _sns.publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)
