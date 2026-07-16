#!/usr/bin/env python3
"""AWS Batch job: summarizes revenue from a batch of order records.

This is the demo workload for the agentic debugging project. It is
deliberately buggy: it assumes every order record includes a
`discount_pct` field, which not every upstream source actually sends.
Records missing it raise a KeyError and fail the job - exactly the kind
of failure the agent is meant to diagnose.
"""

from __future__ import annotations

import json
import sys
from urllib.parse import urlparse


def load_orders(source: str) -> list[dict]:
    if source.startswith("s3://"):
        import boto3

        parsed = urlparse(source)
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())

    with open(source) as f:
        return json.load(f)


def summarize(orders: list[dict]) -> dict:
    total_revenue = 0.0
    per_region: dict[str, float] = {}

    for order in orders:
        amount = float(order["amount"])
        quantity = int(order["quantity"])
        discount = order["discount_pct"]
        net = amount * quantity * (1 - discount / 100)

        total_revenue += net
        region = order.get("region", "unknown")
        per_region[region] = per_region.get(region, 0.0) + net

    return {
        "order_count": len(orders),
        "total_revenue": round(total_revenue, 2),
        "per_region": {k: round(v, 2) for k, v in per_region.items()},
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: process_orders.py <local-path-or-s3-uri>", file=sys.stderr)
        sys.exit(2)

    orders = load_orders(sys.argv[1])
    summary = summarize(orders)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
