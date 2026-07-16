import os

# Must run before any `agent.*` module is imported: several clients construct
# a boto3 client at module import time, which needs a region and (dummy,
# for tests) credentials to exist.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("GITHUB_TOKEN_SECRET_ID", "agentic-batch-debug/github-token")
os.environ.setdefault("ANTHROPIC_API_KEY_SECRET_ID", "agentic-batch-debug/anthropic-api-key")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-topic")
os.environ.setdefault("DLQ_URL", "https://sqs.us-east-1.amazonaws.com/123456789012/test-dlq")
os.environ.setdefault("QUARANTINE_BUCKET", "test-quarantine-bucket")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
