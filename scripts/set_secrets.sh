#!/usr/bin/env bash
# Populates the two Secrets Manager secrets the agent reads at runtime.
# CDK creates the secrets empty (a placeholder value) since secret values
# don't belong in CloudFormation templates or source control.
#
# Required env vars: GITHUB_TOKEN, ANTHROPIC_API_KEY

set -euo pipefail

: "${GITHUB_TOKEN:?Set GITHUB_TOKEN to a PAT with repo scope (contents + pull_requests)}"
: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY to your Anthropic API key}"

aws secretsmanager put-secret-value \
  --secret-id agentic-batch-debug/github-token \
  --secret-string "$GITHUB_TOKEN" >/dev/null

aws secretsmanager put-secret-value \
  --secret-id agentic-batch-debug/anthropic-api-key \
  --secret-string "$ANTHROPIC_API_KEY" >/dev/null

echo "Secrets updated."
