#!/usr/bin/env bash
# Builds the demo container, pushes it to the ECR repo created by
# AgenticBatchDebugDemo, uploads a sample input file to the demo data
# bucket, and submits an AWS Batch job against it.
#
# Usage: ./submit_demo_job.sh [good|bad]
#   good - well-formed input, the job succeeds (nothing for the agent to do)
#   bad  - one record is missing discount_pct, the job fails on purpose (default)

set -euo pipefail

VARIANT="${1:-bad}"
if [[ "$VARIANT" != "good" && "$VARIANT" != "bad" ]]; then
  echo "usage: $0 [good|bad]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_NAME="${STACK_NAME:-AgenticBatchDebugDemo}"

output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

echo "Reading stack outputs from $STACK_NAME..."
ECR_URI="$(output DemoEcrRepoUri)"
DATA_BUCKET="$(output DemoDataBucketName)"
JOB_QUEUE="$(output DemoJobQueueName)"
JOB_DEFINITION="$(output DemoJobDefinitionName)"
REPO_TAG="$(output DemoAgentRepoTag)"
ENTRYPOINT_TAG="$(output DemoAgentEntrypointTag)"
REF_TAG="$(output DemoAgentRefTag)"

REGISTRY="${ECR_URI%%/*}"

echo "Building and pushing demo image to $ECR_URI:latest..."
aws ecr get-login-password --region "${AWS_REGION:-$(aws configure get region)}" \
  | docker login --username AWS --password-stdin "$REGISTRY"
docker build -t "$ECR_URI:latest" "$SCRIPT_DIR"
docker push "$ECR_URI:latest"

INPUT_KEY="inputs/${VARIANT}.json"
echo "Uploading demo/sample_input_${VARIANT}.json to s3://$DATA_BUCKET/$INPUT_KEY..."
aws s3 cp "$SCRIPT_DIR/sample_input_${VARIANT}.json" "s3://$DATA_BUCKET/$INPUT_KEY"

TAGS_JSON=$(cat <<EOF
{"agentic-debug:repo": "$REPO_TAG", "agentic-debug:entrypoint": "$ENTRYPOINT_TAG", "agentic-debug:ref": "$REF_TAG"}
EOF
)

JOB_NAME="demo-orders-${VARIANT}-$(date +%s)"
echo "Submitting job $JOB_NAME to queue $JOB_QUEUE..."
aws batch submit-job \
  --job-name "$JOB_NAME" \
  --job-queue "$JOB_QUEUE" \
  --job-definition "$JOB_DEFINITION" \
  --parameters "inputUri=s3://$DATA_BUCKET/$INPUT_KEY" \
  --tags "$TAGS_JSON"

echo "Submitted. Track it with:"
echo "  aws batch describe-jobs --jobs <job-id-from-above>"
if [[ "$VARIANT" == "bad" ]]; then
  echo "This job is expected to FAIL - watch the AgenticBatchDebugCore alerts SNS topic" \
       "and CloudWatch Logs for the analyzer Lambda to see the agent respond."
fi
