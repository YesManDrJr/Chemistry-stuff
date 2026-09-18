#!/usr/bin/env python3
"""
Attestation Lab
A small, dependency-free CLI for creating GitHub Actions custom attestations.

It does NOT perform the Sigstore signing locally. Instead, it generates a
workflow that uses GitHub's actions/attest@v4 to create the real signed
attestation in GitHub Actions.

Usage:
    python main.py init
    python main.py predicate --comment "Release 1.0" --version 1.0.0
    python main.py workflow --artifact dist/app --build "python build.py"
    python main.py verify --artifact dist/app --repo OWNER/REPO
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


APP_NAME = "Attestation Lab"
DEFAULT_PREDICATE_TYPE = "https://yesmandrjr.dev/attestation/v1"
DEFAULT_WORKFLOW = Path(".github/workflows/attestation.yml")
DEFAULT_PREDICATE = Path(".attestation/predicate.json")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Artifact is not a file: {path}")

    digest = hashlib.sha256()

    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)

    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)

    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")

    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError("This command must be run inside a Git repository.")

    return Path(result.stdout.strip())


def git_remote(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    return result.stdout.strip()


def repo_slug_from_remote(remote: str | None) -> str | None:
    if not remote:
        return None

    remote = remote.removesuffix(".git")

    if remote.startswith("git@github.com:"):
        return remote.split(":", 1)[1]

    marker = "github.com/"
    if marker in remote:
        return remote.split(marker, 1)[1].lstrip("/")

    return None


def build_predicate(
    *,
    artifact: Path | None,
    comment: str,
    version: str,
    author: str,
    channel: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    predicate: dict[str, Any] = {
        "schemaVersion": "1.0",
        "comment": comment,
        "version": version,
        "author": author,
        "channel": channel,
    }

    if artifact is not None:
        predicate["artifact"] = {
            "name": artifact.name,
            "sha256": sha256_file(artifact),
        }

    if extra:
        predicate["metadata"] = extra

    return predicate


def workflow_text(
    *,
    artifact: str,
    build_command: str,
    predicate_type: str,
    predicate_path: str,
) -> str:
    # Artifact path is deliberately inserted as a literal workflow input.
    # This tool is intended for trusted repository configuration.
    return f"""name: Create Attestation

on:
  workflow_dispatch:

permissions:
  id-token: write
  contents: read
  attestations: write
  artifact-metadata: write

jobs:
  attest:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Build artifact
        shell: bash
        run: |
          {build_command}

      - name: Check artifact
        shell: bash
        run: |
          test -f "{artifact}"
          sha256sum "{artifact}"

      - name: Create custom attestation
        uses: actions/attest@v4
        with:
          subject-path: "{artifact}"
          predicate-type: "{predicate_type}"
          predicate-path: "{predicate_path}"
          show-summary: true
"""


def cmd_init(args: argparse.Namespace) -> int:
    root = repo_root()

    workflow = root / DEFAULT_WORKFLOW
    predicate = root / DEFAULT_PREDICATE

    workflow.parent.mkdir(parents=True, exist_ok=True)
    predicate.parent.mkdir(parents=True, exist_ok=True)

    if not predicate.exists():
        write_json(
            predicate,
            {
                "schemaVersion": "1.0",
                "comment": "Describe this artifact.",
                "version": "0.1.0",
                "author": "unknown",
                "channel": "development",
                "metadata": {},
            },
        )

    if not workflow.exists():
        workflow.write_text(
            workflow_text(
                artifact="dist/artifact",
                build_command="echo 'Replace this with your build command'",
                predicate_type=DEFAULT_PREDICATE_TYPE,
                predicate_path=".attestation/predicate.json",
            ),
            encoding="utf-8",
        )

    print(f"{APP_NAME}")
    print(f"Repository: {root}")
    print(f"Predicate:  {predicate}")
    print(f"Workflow:   {workflow}")
    print()
    print("Next: edit the predicate/workflow, then run:")
    print("  gh workflow run attestation.yml")
    return 0


def cmd_predicate(args: argparse.Namespace) -> int:
    root = repo_root()

    artifact = Path(args.artifact).expanduser().resolve() if args.artifact else None

    extra: dict[str, Any] = {}
    if args.metadata:
        try:
            extra = json.loads(args.metadata)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--metadata is not valid JSON: {exc}") from exc

        if not isinstance(extra, dict):
            raise ValueError("--metadata must be a JSON object")

    predicate = build_predicate(
        artifact=artifact,
        comment=args.comment,
        version=args.version,
        author=args.author,
        channel=args.channel,
        extra=extra,
    )

    output = root / args.output
    write_json(output, predicate)

    print(f"Predicate written to: {output}")

    if artifact:
        print(f"Artifact: {artifact}")
        print(f"SHA-256:  {predicate['artifact']['sha256']}")

    return 0


def cmd_workflow(args: argparse.Namespace) -> int:
    root = repo_root()

    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(
        workflow_text(
            artifact=args.artifact,
            build_command=args.build,
            predicate_type=args.predicate_type,
            predicate_path=args.predicate_path,
        ),
        encoding="utf-8",
    )

    print(f"Workflow written to: {output}")
    print()
    print("Workflow configuration:")
    print(f"  Artifact:        {args.artifact}")
    print(f"  Build command:   {args.build}")
    print(f"  Predicate type:  {args.predicate_type}")
    print(f"  Predicate path:  {args.predicate_path}")
    return 0


def cmd_attest(args: argparse.Namespace) -> int:
    root = repo_root()

    workflow_name = Path(args.workflow).name

    if shutil.which("gh") is None:
        raise RuntimeError(
            "GitHub CLI (gh) is not installed. "
            "Install/configure gh, then rerun this command."
        )

    # Check authentication without exposing credentials.
    auth = subprocess.run(
        ["gh", "auth", "status"],
        cwd=root,
        text=True,
    )

    if auth.returncode != 0:
        raise RuntimeError(
            "GitHub CLI is not authenticated. Run: gh auth login"
        )

    command = ["gh", "workflow", "run", workflow_name]

    if args.ref:
        command += ["--ref", args.ref]

    print("Dispatching GitHub Actions workflow...")
    result = subprocess.run(command, cwd=root)

    if result.returncode != 0:
        return result.returncode

    print()
    print("Workflow dispatched.")
    print("Use 'gh run list' to watch it.")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI (gh) is required for verification.")

    command = [
        "gh",
        "attestation",
        "verify",
        args.artifact,
        "-R",
        args.repo,
        "--format",
        "json",
    ]

    if args.predicate_type:
        command += ["--predicate-type", args.predicate_type]

    result = subprocess.run(command, text=True)

    return result.returncode


def cmd_hash(args: argparse.Namespace) -> int:
    path = Path(args.artifact).expanduser().resolve()
    digest = sha256_file(path)

    print(f"artifact: {path}")
    print(f"sha256:  {digest}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="attestation-lab",
        description="Build custom GitHub artifact-attestation workflows.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create starter attestation files.")
    init.set_defaults(func=cmd_init)

    pred = sub.add_parser("predicate", help="Create a custom predicate JSON.")
    pred.add_argument("--artifact", help="Local artifact to hash.")
    pred.add_argument("--comment", required=True)
    pred.add_argument("--version", default="0.1.0")
    pred.add_argument("--author", default="unknown")
    pred.add_argument("--channel", default="development")
    pred.add_argument(
        "--metadata",
        help='Extra JSON object, e.g. \'{"platform":"linux","arch":"amd64"}\'',
    )
    pred.add_argument(
        "--output",
        default=str(DEFAULT_PREDICATE),
    )
    pred.set_defaults(func=cmd_predicate)

    wf = sub.add_parser("workflow", help="Generate the GitHub Actions workflow.")
    wf.add_argument("--artifact", required=True)
    wf.add_argument("--build", required=True)
    wf.add_argument(
        "--predicate-type",
        default=DEFAULT_PREDICATE_TYPE,
    )
    wf.add_argument(
        "--predicate-path",
        default=str(DEFAULT_PREDICATE),
    )
    wf.add_argument(
        "--output",
        default=str(DEFAULT_WORKFLOW),
    )
    wf.set_defaults(func=cmd_workflow)

    run = sub.add_parser(
        "attest",
        help="Dispatch the GitHub Actions attestation workflow.",
    )
    run.add_argument(
        "--workflow",
        default=str(DEFAULT_WORKFLOW),
    )
    run.add_argument("--ref")
    run.set_defaults(func=cmd_attest)

    verify = sub.add_parser(
        "verify",
        help="Verify an attestation with GitHub CLI.",
    )
    verify.add_argument("artifact")
    verify.add_argument("--repo", required=True)
    verify.add_argument("--predicate-type")
    verify.set_defaults(func=cmd_verify)

    h = sub.add_parser("hash", help="Calculate an artifact SHA-256.")
    h.add_argument("artifact")
    h.set_defaults(func=cmd_hash)

    return p


def main() -> int:
    args = parser().parse_args()

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
