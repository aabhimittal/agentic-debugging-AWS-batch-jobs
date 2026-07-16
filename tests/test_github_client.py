import base64
from unittest.mock import MagicMock

from agent.clients import github_client


def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    m.raise_for_status = MagicMock()
    return m


def test_is_successful_commit_true_for_success_state(monkeypatch):
    monkeypatch.setattr(github_client.requests, "get", lambda *a, **k: _resp(200, {"state": "success"}))
    assert github_client._is_successful_commit("o/r", "sha", {}) is True


def test_is_successful_commit_true_when_no_checks_configured(monkeypatch):
    monkeypatch.setattr(
        github_client.requests, "get", lambda *a, **k: _resp(200, {"state": "pending", "total_count": 0})
    )
    assert github_client._is_successful_commit("o/r", "sha", {}) is True


def test_is_successful_commit_false_for_failure_state(monkeypatch):
    monkeypatch.setattr(
        github_client.requests, "get", lambda *a, **k: _resp(200, {"state": "failure", "total_count": 1})
    )
    assert github_client._is_successful_commit("o/r", "sha", {}) is False


def test_get_file_content_decodes_base64(monkeypatch):
    content = base64.b64encode(b"print('hi')").decode()
    monkeypatch.setattr(github_client.requests, "get", lambda *a, **k: _resp(200, {"content": content}))
    result = github_client.get_file_content("o/r", "f.py", "main", "tok")
    assert result == "print('hi')"


def test_get_file_content_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(github_client.requests, "get", lambda *a, **k: _resp(404))
    assert github_client.get_file_content("o/r", "missing.py", "main", "tok") is None


def test_get_last_successful_commits_filters_failed_and_stops_at_count(monkeypatch):
    commit_states = {"sha0": "success", "sha1": "failure", "sha2": "success", "sha3": "success", "sha4": "success"}
    commits_page = [
        {"sha": sha, "commit": {"message": f"m-{sha}", "author": {"name": "a", "date": "d"}}}
        for sha in commit_states
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/status"):
            sha = url.split("/commits/")[1].split("/status")[0]
            return _resp(200, {"state": commit_states[sha], "total_count": 1})
        if url.endswith("/commits"):
            page = params.get("page", 1)
            return _resp(200, commits_page if page == 1 else [])
        return _resp(200, {"files": []})

    monkeypatch.setattr(github_client.requests, "get", fake_get)

    commits = github_client.get_last_successful_commits("o/r", "tok", count=3)

    assert len(commits) == 3
    assert all(c.sha != "sha1" for c in commits)


def test_create_fix_pr_returns_html_url(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(("GET", url))
        if url.endswith("/git/ref/heads/main"):
            return _resp(200, {"object": {"sha": "base-sha"}})
        if "/contents/" in url:
            return _resp(404)  # file doesn't exist on the new branch yet
        return _resp(404)

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url))
        if url.endswith("/git/refs"):
            return _resp(201, {})
        if url.endswith("/pulls"):
            return _resp(201, {"html_url": "https://github.com/o/r/pull/42"})
        return _resp(404)

    def fake_put(url, headers=None, json=None, timeout=None):
        calls.append(("PUT", url))
        return _resp(200, {})

    monkeypatch.setattr(github_client.requests, "get", fake_get)
    monkeypatch.setattr(github_client.requests, "post", fake_post)
    monkeypatch.setattr(github_client.requests, "put", fake_put)

    pr_url = github_client.create_fix_pr(
        repo="o/r",
        base_ref="main",
        file_path="demo/process_orders.py",
        new_content="print('fixed')",
        root_cause="KeyError on discount_pct",
        explanation="added a default",
        job_id="job-1",
        token="tok",
    )

    assert pr_url == "https://github.com/o/r/pull/42"
    assert ("POST", "https://api.github.com/repos/o/r/pulls") in calls
