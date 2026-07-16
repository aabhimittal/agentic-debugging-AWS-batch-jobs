#!/usr/bin/env python3
"""Run the agent's diagnosis step locally, against a hand-crafted job
failure, without touching AWS at all. Useful for iterating on the prompt,
or for trying the agent against your own repo's real commit history.

Example (using the demo's canned failure):

    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python3 scripts/local_dry_run.py \\
        --repo <owner>/<repo> --entrypoint demo/process_orders.py \\
        --log-file demo/sample_failure_log.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.clients import github_client, llm_client  # noqa: E402
from agent.models import JobContext  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--entrypoint", required=True, help="repo-relative path to the failing script")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--log-file", required=True, help="path to a text file with the failure's log tail")
    args = parser.parse_args()

    github_token = os.environ["GITHUB_TOKEN"]
    log_tail = Path(args.log_file).read_text()

    job = JobContext(
        job_id="local-dry-run",
        job_name="local-dry-run",
        job_definition="local",
        job_queue="local",
        status="FAILED",
        status_reason="Essential container in task exited",
        exit_code=1,
        log_group="local",
        log_stream_name="local",
        container_image="local",
        tags={
            "agentic-debug:repo": args.repo,
            "agentic-debug:entrypoint": args.entrypoint,
            "agentic-debug:ref": args.ref,
        },
    )

    print(f"Fetching last 10 successful commits to {args.entrypoint} on {args.repo}@{args.ref}...")
    commits = github_client.get_last_successful_commits(
        args.repo, github_token, ref=args.ref, path=args.entrypoint, count=10
    )
    print(f"Found {len(commits)} commit(s).")

    file_content = github_client.get_file_content(args.repo, args.entrypoint, args.ref, github_token)

    print("Calling Claude...")
    decision = llm_client.analyze(job, log_tail, commits, args.entrypoint, file_content)

    print()
    print(f"action:      {decision.action.value}")
    print(f"confidence:  {decision.confidence}")
    print(f"root_cause:  {decision.root_cause}")
    print(f"explanation: {decision.explanation}")
    if decision.action.value == "fix":
        print(f"fix_file_path: {decision.fix_file_path}")
        print("suggested_fix:")
        print(decision.suggested_fix)
    else:
        print(f"reroute_reason: {decision.reroute_reason}")


if __name__ == "__main__":
    main()
