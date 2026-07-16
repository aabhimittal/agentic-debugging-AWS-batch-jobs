"""Secrets Manager client with a process-level cache for Lambda warm starts."""

from __future__ import annotations

import boto3

_secretsmanager = boto3.client("secretsmanager")
_cache: dict[str, str] = {}


def get_secret(secret_id: str) -> str:
    if secret_id not in _cache:
        resp = _secretsmanager.get_secret_value(SecretId=secret_id)
        _cache[secret_id] = resp["SecretString"]
    return _cache[secret_id]
