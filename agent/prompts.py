"""Prompt construction for the batch-failure diagnosis agent."""

from __future__ import annotations

from agent.models import Commit, JobContext

SYSTEM_PROMPT = """\
You are an on-call SRE agent for an AWS Batch data pipeline. A Batch job has \
failed and you must decide how to respond. You are given the job's metadata, \
the tail of its CloudWatch logs, the current contents of the script the job \
runs, and the last several commits made to that script.

You have exactly two possible actions, and must pick one:

1. "fix" - You are confident the failure is caused by a bug in the script \
   itself (not bad input data, not a transient infra issue, not a missing \
   permission) and you can write a corrected version of the file that \
   resolves the root cause without changing unrelated behavior. Use this only \
   when your confidence is reasonably high; an incorrect automated fix that \
   gets merged is worse than no fix.
2. "reroute" - The failure is caused by something other than a fixable code \
   bug (malformed/unexpected input data, a data contract violation, a \
   transient dependency error, missing configuration, etc.), or you are not \
   confident enough in a specific code fix. In this case the job's input \
   should be routed to a Dead Letter Queue for a specialized recovery \
   process to inspect, rather than guessing at a code change.

Always call the submit_decision tool exactly once with your conclusion. When \
action is "fix", you MUST include the complete corrected file contents in \
suggested_fix (not a diff) and the exact fix_file_path that was given to you. \
When action is "reroute", you MUST include a reroute_reason explaining what a \
recovery script should look for. Be concise but specific in root_cause and \
explanation - reference exact log lines, exception types, or commit SHAs \
where relevant.
"""


def build_user_prompt(
    job: JobContext,
    log_tail: str,
    commits: list[Commit],
    file_path: str | None,
    file_content: str | None,
) -> str:
    commit_block = (
        "\n\n".join(c.to_prompt_block() for c in commits)
        if commits
        else "(no commit history available)"
    )
    file_block = (
        f"### Current contents of {file_path}\n```python\n{file_content}\n```"
        if file_path and file_content is not None
        else "(no source file was resolved for this job - you cannot propose a code fix; "
        "you must choose reroute)"
    )

    return f"""\
### Failed job
job_id: {job.job_id}
job_name: {job.job_name}
job_definition: {job.job_definition}
job_queue: {job.job_queue}
status: {job.status}
status_reason: {job.status_reason}
exit_code: {job.exit_code}
container_image: {job.container_image}
parameters: {job.parameters}

### Log tail ({job.log_group}/{job.log_stream_name})
```
{log_tail.strip() or "(no logs retrieved)"}
```

### Last {len(commits)} commits to {file_path or "the source repo"}
{commit_block}

{file_block}

Diagnose the root cause and submit your decision via the submit_decision tool.
"""
