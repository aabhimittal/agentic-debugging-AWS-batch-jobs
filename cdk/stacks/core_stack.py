"""Core agent infrastructure: the EventBridge trigger, the two Lambda
functions, the Dead Letter Queue, the quarantine bucket, secrets, and the
alerting topic. Wire this to your own AWS Batch jobs by tagging them (see
README) - it does not depend on the demo stack at all.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    Aws,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from stacks.lambda_bundling import agent_lambda_code

REPO_ROOT = Path(__file__).resolve().parents[2]


class CoreStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alert_email: str | None = None,
        default_github_repo: str | None = None,
        default_entrypoint: str | None = None,
        default_ref: str = "main",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        github_token_secret = secretsmanager.Secret(
            self,
            "GitHubTokenSecret",
            secret_name="agentic-batch-debug/github-token",
            description="GitHub PAT (repo scope) used by the agent to read commit history, "
            "read source files, and open fix PRs. Set the value after deploy.",
        )
        anthropic_secret = secretsmanager.Secret(
            self,
            "AnthropicApiKeySecret",
            secret_name="agentic-batch-debug/anthropic-api-key",
            description="Anthropic API key used by the agent to call Claude. Set the value after deploy.",
        )

        dlq = sqs.Queue(
            self,
            "BatchDeadLetterQueue",
            queue_name="agentic-batch-debug-dlq",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
        )

        quarantine_bucket = s3.Bucket(
            self,
            "QuarantineBucket",
            bucket_name=f"agentic-batch-debug-quarantine-{Aws.ACCOUNT_ID}-{Aws.REGION}",
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )

        alerts_topic = sns.Topic(self, "AgentAlertsTopic", topic_name="agentic-batch-debug-alerts")
        if alert_email:
            alerts_topic.add_subscription(sns_subs.EmailSubscription(alert_email))

        common_env = {
            "GITHUB_TOKEN_SECRET_ID": github_token_secret.secret_name,
            "ANTHROPIC_API_KEY_SECRET_ID": anthropic_secret.secret_name,
            "SNS_TOPIC_ARN": alerts_topic.topic_arn,
            "DLQ_URL": dlq.queue_url,
            "QUARANTINE_BUCKET": quarantine_bucket.bucket_name,
            "AUTO_RESUBMIT": "false",
            "DEFAULT_REF": default_ref,
        }
        if default_github_repo:
            common_env["DEFAULT_GITHUB_REPO"] = default_github_repo
        if default_entrypoint:
            common_env["DEFAULT_ENTRYPOINT"] = default_entrypoint

        code = agent_lambda_code(REPO_ROOT)

        analyzer_fn = _lambda.Function(
            self,
            "AnalyzerFunction",
            function_name="agentic-batch-debug-analyzer",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.X86_64,
            handler="agent.analyzer_handler.handler",
            code=code,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=common_env,
        )

        recovery_fn = _lambda.Function(
            self,
            "RecoveryFunction",
            function_name="agentic-batch-debug-recovery",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.X86_64,
            handler="agent.recovery_handler.handler",
            code=code,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=common_env,
        )
        recovery_fn.add_event_source(lambda_event_sources.SqsEventSource(dlq, batch_size=1))

        # --- Permissions -----------------------------------------------
        github_token_secret.grant_read(analyzer_fn)
        anthropic_secret.grant_read(analyzer_fn)
        alerts_topic.grant_publish(analyzer_fn)
        alerts_topic.grant_publish(recovery_fn)
        dlq.grant_send_messages(analyzer_fn)
        quarantine_bucket.grant_read_write(recovery_fn)

        analyzer_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["batch:DescribeJobs"],
                resources=["*"],  # DescribeJobs has no resource-level ARN support
            )
        )
        analyzer_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["logs:GetLogEvents", "logs:DescribeLogStreams"],
                resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/batch/job:*"],
            )
        )
        recovery_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["batch:SubmitJob"],
                resources=["*"],  # SubmitJob targets vary per job/queue/definition ARN+revision
            )
        )

        rule = events.Rule(
            self,
            "BatchJobFailedRule",
            rule_name="agentic-batch-debug-job-failed",
            event_pattern=events.EventPattern(
                source=["aws.batch"],
                detail_type=["Batch Job State Change"],
                detail={"status": ["FAILED"]},
            ),
        )
        rule.add_target(targets.LambdaFunction(analyzer_fn, retry_attempts=2))

        self.analyzer_function = analyzer_fn
        self.recovery_function = recovery_fn
        self.dead_letter_queue = dlq
        self.quarantine_bucket = quarantine_bucket
        self.alerts_topic = alerts_topic

        CfnOutput(self, "GitHubTokenSecretName", value=github_token_secret.secret_name)
        CfnOutput(self, "AnthropicApiKeySecretName", value=anthropic_secret.secret_name)
        CfnOutput(self, "DeadLetterQueueUrl", value=dlq.queue_url)
        CfnOutput(self, "QuarantineBucketName", value=quarantine_bucket.bucket_name)
        CfnOutput(self, "AlertsTopicArn", value=alerts_topic.topic_arn)
