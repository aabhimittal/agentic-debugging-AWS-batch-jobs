# agentic-debugging-AWS-batch-jobs

When an AWS Batch job fails, an LLM agent automatically diagnoses it: it
reads the job's CloudWatch logs and the last 10 successful commits to the
script the job runs, then either **opens a GitHub PR with a suggested code
fix**, or **reroutes the job's input to a Dead Letter Queue** for a
specialized recovery script - whichever it decides is the safer, more
appropriate response.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design, a sequence
diagram, and the reasoning behind each infrastructure choice. This README is
the step-by-step build-and-run guide.

## How it decides

```
Batch job fails
      |
      v
EventBridge rule (status=FAILED) --> Analyzer Lambda
      |
      v
Gather context: job metadata + log tail + last 10 successful
commits to the job's script + the script's current contents
      |
      v
Claude (tool-use, forced call to `submit_decision`)
      |
      +-- action=fix ------> open a GitHub PR with the corrected file
      |
      +-- action=reroute --> send to SQS DLQ --> Recovery Lambda
                                                  cleans/validates input,
                                                  optionally resubmits
```

Both paths end with an SNS notification. See
[ARCHITECTURE.md](./ARCHITECTURE.md#why-these-choices) for why fixes are
full-file replacements (not diffs), and for the code-level guardrail that
stops the agent from opening a PR if it doesn't actually have enough
context to do so safely.

## Repository layout

```
agent/                  the Lambda application code
  analyzer_handler.py    EventBridge-triggered: diagnose + act
  recovery_handler.py    SQS-triggered: run the recovery script
  models.py               shared dataclasses
  prompts.py               system/user prompt construction
  clients/                 boto3 / GitHub / Anthropic wrappers
  recovery/                the specialized DLQ recovery logic
cdk/                     AWS CDK (Python) infrastructure
  stacks/core_stack.py     EventBridge, Lambdas, DLQ, secrets, SNS
  stacks/demo_stack.py     optional: Fargate Batch env + demo job def
demo/                    a deliberately buggy sample Batch job
  process_orders.py        the "application" the demo job runs
  submit_demo_job.sh        build/push/submit a demo run
scripts/                 deploy.sh, set_secrets.sh, local_dry_run.py
tests/                   pytest suite (no AWS credentials required)
```

## Prerequisites

- An AWS account with permission to create the resources below, and the
  AWS CLI configured (`aws configure`) or credentials in your environment.
- Python 3.12, Node.js 18+ (for the CDK CLI), and Docker (only needed if
  local Lambda dependency bundling falls back to Docker - see
  [ARCHITECTURE.md](./ARCHITECTURE.md#why-these-choices)).
- A GitHub [personal access token](https://github.com/settings/tokens) with
  `repo` scope (contents + pull requests) on the repository you want the
  agent to read from and open PRs against.
- An [Anthropic API key](https://console.anthropic.com/).

## 1. Install dependencies

```bash
pip install -r requirements-dev.txt   # agent runtime deps + pytest + ruff
pip install -r cdk/requirements.txt   # CDK (or let scripts/deploy.sh do this in a venv)
npm install -g aws-cdk@2              # CDK CLI (or let scripts/deploy.sh use npx)
```

## 2. Run the tests

Nothing here talks to AWS - every client is mocked/monkeypatched.

```bash
python -m pytest -q
ruff check agent demo scripts cdk tests
```

## 3. Deploy the infrastructure

```bash
export GITHUB_REPO="<your-github-username-or-org>/<repo>"
export ALERT_EMAIL="you@example.com"   # optional, subscribes to the SNS alerts topic
./scripts/deploy.sh
```

This bootstraps CDK (first time only) and deploys both stacks:

- **`AgenticBatchDebugCore`** - the EventBridge rule, the two Lambdas, the
  DLQ, the quarantine S3 bucket, two empty Secrets Manager secrets, and the
  SNS alerts topic. Deploy this alone (`DEPLOY_DEMO=false ./scripts/deploy.sh`)
  if you're wiring the agent to your own existing Batch jobs.
- **`AgenticBatchDebugDemo`** - a minimal Fargate Batch compute
  environment/queue/job definition, an ECR repo, and a scratch S3 bucket, so
  you can see the whole loop end to end without touching production
  infrastructure.

## 4. Set the secrets

CDK creates the two secrets empty on purpose (secret values don't belong in
CloudFormation templates or source control):

```bash
export GITHUB_TOKEN="ghp_..."
export ANTHROPIC_API_KEY="sk-ant-..."
./scripts/set_secrets.sh
```

## 5. Run the demo

```bash
./demo/submit_demo_job.sh bad
```

This builds `demo/process_orders.py` into a container, pushes it to the
demo ECR repo, uploads `demo/sample_input_bad.json` (one order record is
missing `discount_pct`) to the demo data bucket, and submits an AWS Batch
job against it. The job fails with a `KeyError`, exactly like the traceback
in `demo/sample_failure_log.txt`.

Within roughly a minute you should see:

1. An email/SNS notification (if you set `ALERT_EMAIL`) describing the
   agent's decision.
2. Either a **new pull request** on your `GITHUB_REPO` (branch
   `agentic-fix/job-<job-id>`) with a corrected `demo/process_orders.py`, or
   a **CloudWatch Logs entry** for the recovery Lambda showing it cleaned
   the bad record and quarantined it (recovery defaults to
   `AUTO_RESUBMIT=false`, so nothing is auto-resubmitted unless you opt in).

Run `./demo/submit_demo_job.sh good` to submit a well-formed batch and
confirm the job succeeds normally (the agent never runs - it's only
triggered by `FAILED` state changes).

Watch it happen from the CLI:

```bash
aws logs tail /aws/lambda/agentic-batch-debug-analyzer --follow
aws logs tail /aws/lambda/agentic-batch-debug-recovery --follow
```

## 6. Wire it to your own Batch jobs

You don't need the demo stack at all for this - deploy just
`AgenticBatchDebugCore` (`DEPLOY_DEMO=false ./scripts/deploy.sh`), then tag
each Batch job at submission time so the agent knows which repo/file backs
it:

```bash
aws batch submit-job \
  --job-name my-real-job \
  --job-queue my-queue \
  --job-definition my-job-def \
  --tags '{"agentic-debug:repo": "myorg/myrepo", "agentic-debug:entrypoint": "pipelines/etl.py", "agentic-debug:ref": "main"}'
```

(Job *definition* tags are not inherited by submitted jobs - see the note
in `cdk/stacks/demo_stack.py` - so pass these at `submit-job` time, or set
`DEFAULT_GITHUB_REPO` / `DEFAULT_ENTRYPOINT` / `DEFAULT_REF` on the analyzer
Lambda if every job in your account maps to the same repo/file.)

## Local development

Iterate on the prompt or try the agent against your own repo's real commit
history without touching AWS at all:

```bash
GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python3 scripts/local_dry_run.py \
  --repo myorg/myrepo --entrypoint path/to/script.py \
  --log-file demo/sample_failure_log.txt
```

## Cost and cleanup

The core stack is essentially free at rest (Lambda, SQS, SNS, Secrets
Manager all bill per-use). The demo stack's VPC has no NAT gateway (Fargate
tasks get public IPs directly), so the only ongoing cost is the S3/ECR
storage for whatever you've pushed. Tear everything down with:

```bash
cd cdk && cdk destroy --all
```

You may need to empty the demo ECR repository first (`aws ecr batch-delete-image`
or the console) if CDK can't delete a non-empty repo.

## Security notes

- Each Lambda's IAM role is scoped to only what it needs (see
  `cdk/stacks/core_stack.py`): the analyzer can describe Batch jobs, read
  its two secrets, read logs, publish to SNS, and send to the DLQ; the
  recovery function can consume from the DLQ, read/write the quarantine
  bucket, submit new Batch jobs, and publish to SNS. Neither has broad
  `s3:*` or `iam:*` access.
- GitHub and Anthropic credentials live in Secrets Manager, fetched at
  Lambda runtime and cached per warm start - never logged, never in
  environment variables in the CDK templates.
- The "fix" path always goes through a **pull request**, never a direct
  push to a protected branch - combine this with GitHub branch protection
  and required reviews so a human always approves before an agent-authored
  change merges.
