"""GitHub REST API client: read commit history/source, and open fix PRs.

Uses plain HTTP (no PyGithub dependency) to keep the Lambda deployment
package small.
"""

from __future__ import annotations

import base64

import requests

from agent.models import Commit

API_BASE = "https://api.github.com"
_TIMEOUT = 15


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _is_successful_commit(repo: str, sha: str, headers: dict[str, str]) -> bool:
    """A commit counts as "successful" if its combined CI status is green,
    or if the repo has no CI configured at all (nothing to have failed)."""
    resp = requests.get(f"{API_BASE}/repos/{repo}/commits/{sha}/status", headers=headers, timeout=_TIMEOUT)
    if resp.status_code != 200:
        return True
    data = resp.json()
    state = data.get("state")
    if state == "success":
        return True
    if state == "pending" and data.get("total_count", 0) == 0:
        return True
    return False


def _to_commit(repo: str, raw: dict, headers: dict[str, str]) -> Commit:
    sha = raw["sha"]
    commit_meta = raw["commit"]
    files_changed: list[str] = []
    diff_parts: list[str] = []

    detail_resp = requests.get(f"{API_BASE}/repos/{repo}/commits/{sha}", headers=headers, timeout=_TIMEOUT)
    if detail_resp.status_code == 200:
        for f in detail_resp.json().get("files", [])[:10]:
            files_changed.append(f["filename"])
            patch = f.get("patch")
            if patch:
                diff_parts.append(f"--- {f['filename']}\n{patch}")

    return Commit(
        sha=sha,
        message=commit_meta["message"],
        author=commit_meta.get("author", {}).get("name", "unknown"),
        date=commit_meta.get("author", {}).get("date", ""),
        files_changed=files_changed,
        diff="\n\n".join(diff_parts)[:4000],
    )


def get_last_successful_commits(
    repo: str,
    token: str,
    ref: str = "main",
    path: str | None = None,
    count: int = 10,
    max_pages: int = 5,
) -> list[Commit]:
    headers = _headers(token)
    commits: list[Commit] = []
    per_page = min(max(count * 3, 10), 100)

    for page in range(1, max_pages + 1):
        if len(commits) >= count:
            break
        params: dict[str, str | int] = {"sha": ref, "per_page": per_page, "page": page}
        if path:
            params["path"] = path
        resp = requests.get(f"{API_BASE}/repos/{repo}/commits", headers=headers, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        page_commits = resp.json()
        if not page_commits:
            break
        for raw in page_commits:
            if len(commits) >= count:
                break
            if _is_successful_commit(repo, raw["sha"], headers):
                commits.append(_to_commit(repo, raw, headers))

    return commits


def get_file_content(repo: str, path: str, ref: str, token: str) -> str | None:
    resp = requests.get(
        f"{API_BASE}/repos/{repo}/contents/{path}",
        headers=_headers(token),
        params={"ref": ref},
        timeout=_TIMEOUT,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8")


def create_fix_pr(
    repo: str,
    base_ref: str,
    file_path: str,
    new_content: str,
    root_cause: str,
    explanation: str,
    job_id: str,
    token: str,
) -> str:
    headers = _headers(token)

    ref_resp = requests.get(f"{API_BASE}/repos/{repo}/git/ref/heads/{base_ref}", headers=headers, timeout=_TIMEOUT)
    ref_resp.raise_for_status()
    base_sha = ref_resp.json()["object"]["sha"]

    branch_name = f"agentic-fix/job-{job_id}"[:100]
    create_ref_resp = requests.post(
        f"{API_BASE}/repos/{repo}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        timeout=_TIMEOUT,
    )
    if create_ref_resp.status_code not in (200, 201) and create_ref_resp.status_code != 422:
        create_ref_resp.raise_for_status()

    file_resp = requests.get(
        f"{API_BASE}/repos/{repo}/contents/{file_path}",
        headers=headers,
        params={"ref": branch_name},
        timeout=_TIMEOUT,
    )
    file_sha = file_resp.json().get("sha") if file_resp.status_code == 200 else None

    commit_body: dict[str, str] = {
        "message": f"agentic-fix: {root_cause[:60]}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": branch_name,
    }
    if file_sha:
        commit_body["sha"] = file_sha

    put_resp = requests.put(
        f"{API_BASE}/repos/{repo}/contents/{file_path}", headers=headers, json=commit_body, timeout=_TIMEOUT
    )
    put_resp.raise_for_status()

    pr_body = (
        f"### Root cause\n{root_cause}\n\n"
        f"### Explanation\n{explanation}\n\n"
        f"### Triggering job\n`{job_id}`\n\n"
        "This PR was opened automatically by the agentic AWS Batch debugging "
        "agent in response to a job failure. Please review carefully before merging."
    )
    pr_resp = requests.post(
        f"{API_BASE}/repos/{repo}/pulls",
        headers=headers,
        json={
            "title": f"Agentic fix: {root_cause[:72]}",
            "head": branch_name,
            "base": base_ref,
            "body": pr_body,
        },
        timeout=_TIMEOUT,
    )
    pr_resp.raise_for_status()
    return pr_resp.json()["html_url"]
