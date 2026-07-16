#!/usr/bin/env bash
# Bootstraps and deploys both CDK stacks.
#
# Required:
#   GITHUB_REPO   owner/name of the repo the agent should read/patch
# Optional:
#   ALERT_EMAIL   email address subscribed to the SNS alerts topic
#   DEPLOY_DEMO   "true" (default) or "false" - set false to deploy only
#                 the core agent stack against your own existing Batch jobs

set -euo pipefail

: "${GITHUB_REPO:?Set GITHUB_REPO=owner/name}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
DEPLOY_DEMO="${DEPLOY_DEMO:-true}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$SCRIPT_DIR/../cdk"

cd "$CDK_DIR"
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

CONTEXT_ARGS=(-c "githubRepo=$GITHUB_REPO" -c "deployDemo=$DEPLOY_DEMO")
if [[ -n "$ALERT_EMAIL" ]]; then
  CONTEXT_ARGS+=(-c "alertEmail=$ALERT_EMAIL")
fi

npx --yes aws-cdk@2 bootstrap "${CONTEXT_ARGS[@]}"
npx --yes aws-cdk@2 deploy --all --require-approval never "${CONTEXT_ARGS[@]}"

echo
echo "Deployed. Next: run scripts/set_secrets.sh to configure GITHUB_TOKEN and ANTHROPIC_API_KEY."
