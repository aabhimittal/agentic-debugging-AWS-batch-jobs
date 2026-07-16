import json

from agent.recovery import recovery_script


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3:
    """Minimal in-memory stand-in for the S3 operations recovery_script uses."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def get_object(self, Bucket, Key):  # noqa: N803 (matches boto3's call signature)
        return {"Body": _FakeBody(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.encode()

    def list_objects_v2(self, Bucket, Prefix):  # noqa: N803
        contents = [{"Key": key} for (bucket, key) in self.objects if bucket == Bucket and key.startswith(Prefix)]
        return {"Contents": contents} if contents else {}


def test_clean_orders_splits_valid_and_invalid():
    orders = [
        {"order_id": "1", "amount": "10.00", "quantity": "2", "discount_pct": 0},
        {"order_id": "2", "amount": "20.00", "quantity": "1"},  # missing discount_pct -> defaulted, kept
        {"order_id": "3", "quantity": "1"},  # missing amount -> dropped
    ]
    clean, dropped = recovery_script._clean_orders(orders)

    assert len(clean) == 2
    assert len(dropped) == 1
    assert clean[1]["discount_pct"] == 0


def test_run_skips_when_no_s3_input():
    result = recovery_script.run({"job_id": "job-3", "parameters": {}})
    assert result.status == "skipped"


def test_run_quarantines_without_resubmitting_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_RESUBMIT", raising=False)
    monkeypatch.setenv("QUARANTINE_BUCKET", "quarantine-bucket")

    fake_s3 = _FakeS3()
    orders = [
        {"order_id": "1", "amount": "10.00", "quantity": "2", "discount_pct": 0},
        {"order_id": "2", "quantity": "1"},  # missing amount entirely -> dropped
    ]
    fake_s3.objects[("data-bucket", "in.json")] = json.dumps(orders).encode()
    monkeypatch.setattr(recovery_script, "_s3", fake_s3)

    monkeypatch.setattr(recovery_script.notify_client, "publish", lambda *a, **k: None)
    resubmit_calls = []
    monkeypatch.setattr(
        recovery_script.batch_client, "resubmit_job", lambda **kw: resubmit_calls.append(kw) or "new-job-id"
    )

    message = {
        "job_id": "job-1",
        "job_name": "demo",
        "job_queue": "q",
        "job_definition": "d",
        "parameters": {"inputUri": "s3://data-bucket/in.json"},
        "tags": {},
        "root_cause": "bad data",
        "_recovered_at": "2024-01-01T00:00:00+00:00",
    }
    result = recovery_script.run(message)

    assert result.status == "quarantined"
    assert not resubmit_calls

    quarantine_key = ("quarantine-bucket", "quarantine/job-1/2024-01-01T00:00:00+00:00.json")
    assert quarantine_key in fake_s3.objects
    body = json.loads(fake_s3.objects[quarantine_key])
    assert len(body["dropped_records"]) == 1


def test_run_resubmits_when_auto_resubmit_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_RESUBMIT", "true")
    monkeypatch.setenv("QUARANTINE_BUCKET", "quarantine-bucket")

    fake_s3 = _FakeS3()
    orders = [{"order_id": "1", "amount": "10.00", "quantity": "2", "discount_pct": 0}]
    fake_s3.objects[("data-bucket", "in.json")] = json.dumps(orders).encode()
    monkeypatch.setattr(recovery_script, "_s3", fake_s3)

    monkeypatch.setattr(recovery_script.notify_client, "publish", lambda *a, **k: None)
    resubmit_calls = []
    monkeypatch.setattr(
        recovery_script.batch_client, "resubmit_job", lambda **kw: resubmit_calls.append(kw) or "new-job-id"
    )

    message = {
        "job_id": "job-1",
        "job_name": "demo",
        "job_queue": "q",
        "job_definition": "d",
        "parameters": {"inputUri": "s3://data-bucket/in.json"},
        "tags": {},
        "root_cause": "bad data",
        "_recovered_at": "2024-01-01T00:00:00+00:00",
    }
    result = recovery_script.run(message)

    assert result.status == "resubmitted"
    assert result.resubmitted_job_id == "new-job-id"
    assert len(resubmit_calls) == 1
    assert (
        resubmit_calls[0]["parameters"]["inputUri"]
        == "s3://data-bucket/recovered/job-1/2024-01-01T00:00:00+00:00.json"
    )
    assert ("data-bucket", "recovered/job-1/2024-01-01T00:00:00+00:00.json") in fake_s3.objects
