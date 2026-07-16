"""Local (Docker-free) bundling for the agent Lambda package, with a Docker
fallback for full platform fidelity when local bundling isn't possible."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import jsii
from aws_cdk import BundlingOptions, ILocalBundling
from aws_cdk import aws_lambda as _lambda


@jsii.implements(ILocalBundling)
class _PipLocalBundling:
    def __init__(self, source_root: Path):
        self._source_root = source_root

    def try_bundle(self, output_dir: str, options) -> bool:  # noqa: ARG002
        try:
            subprocess.run(
                [
                    "pip",
                    "install",
                    "--platform",
                    "manylinux2014_x86_64",
                    "--implementation",
                    "cp",
                    "--only-binary=:all:",
                    "-r",
                    str(self._source_root / "requirements.txt"),
                    "-t",
                    output_dir,
                ],
                check=True,
                capture_output=True,
            )
        except Exception:
            return False
        shutil.copytree(self._source_root / "agent", Path(output_dir) / "agent", dirs_exist_ok=True)
        return True


def agent_lambda_code(repo_root: Path) -> _lambda.Code:
    """Bundles the `agent/` package plus its runtime dependencies for Lambda.

    Tries a local `pip install` first (fast, no Docker required); falls back
    to Docker-based bundling (matches the Lambda execution environment
    exactly) if that fails, e.g. for packages with native extensions.
    """
    return _lambda.Code.from_asset(
        str(repo_root),
        exclude=["cdk", "cdk.out", "tests", "demo", ".git", ".venv", "__pycache__"],
        bundling=BundlingOptions(
            image=_lambda.Runtime.PYTHON_3_12.bundling_image,
            command=[
                "bash",
                "-c",
                "pip install -r requirements.txt -t /asset-output && cp -au agent /asset-output",
            ],
            local=_PipLocalBundling(repo_root),
        ),
    )
