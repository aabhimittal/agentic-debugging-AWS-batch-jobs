#!/usr/bin/env python3
"""CDK entrypoint. Run from the `cdk/` directory (see README for the full
deploy walkthrough):

    cd cdk
    pip install -r requirements.txt
    cdk deploy --all -c githubRepo=<owner>/<repo> -c alertEmail=you@example.com

Pass `-c deployDemo=false` to deploy only the core agent stack, e.g. when
wiring the agent to your own existing Batch jobs instead of the demo.
"""

import os

import aws_cdk as cdk
from stacks.core_stack import CoreStack
from stacks.demo_stack import DemoStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

github_repo = app.node.try_get_context("githubRepo") or os.environ.get("GITHUB_REPO", "")
alert_email = app.node.try_get_context("alertEmail") or os.environ.get("ALERT_EMAIL")
_deploy_demo_raw = app.node.try_get_context("deployDemo") or os.environ.get("DEPLOY_DEMO", "true")
deploy_demo = str(_deploy_demo_raw).lower() != "false"

core_stack = CoreStack(
    app,
    "AgenticBatchDebugCore",
    env=env,
    alert_email=alert_email,
    default_github_repo=github_repo or None,
    default_entrypoint="demo/process_orders.py",
    default_ref="main",
)

if deploy_demo:
    DemoStack(
        app,
        "AgenticBatchDebugDemo",
        env=env,
        recovery_function=core_stack.recovery_function,
        github_repo=github_repo,
        entrypoint="demo/process_orders.py",
        ref="main",
    )

app.synth()
