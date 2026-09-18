# Attestation Lab

A small Python tool for creating and verifying GitHub artifact attestations.

## Important architecture

The Python program does not generate a fake/local signature.

It prepares the custom predicate and GitHub Actions workflow. The workflow
uses `actions/attest@v4`, which creates the real signed attestation through
GitHub's attestation/Sigstore infrastructure.

## Requirements

- Python 3.10+
- Git
- A GitHub repository
- GitHub CLI (`gh`) for dispatching/verifying
- A repository where artifact attestations are available
- GitHub Actions enabled

Authenticate the GitHub CLI:

```bash
gh auth login
```

## Quick start

From inside a Git repository:

```bash
python main.py init
```

Create a predicate:

```bash
python main.py predicate \
  --artifact dist/my-program \
  --comment "Official release build" \
  --version 1.0.0 \
  --author YesManDrJr \
  --channel stable \
  --metadata '{"platform":"linux","arch":"amd64"}'
```

Generate a workflow:

```bash
python main.py workflow \
  --artifact dist/my-program \
  --build "python build.py"
```

The workflow will build the artifact on GitHub's runner and then create a
custom attestation for it.

Dispatch it:

```bash
python main.py attest
```

Watch runs:

```bash
gh run list
```

Verify after the workflow succeeds:

```bash
python main.py verify \
  dist/my-program \
  --repo YesManDrJr/example \
  --predicate-type https://yesmandrjr.dev/attestation/v1
```

## Custom predicate

The generated predicate is ordinary JSON. Keep the predicate type under a
stable URI that you control, for example:

```text
https://yesmandrjr.dev/attestation/v1
```

Do not put secrets, tokens, passwords, or other sensitive credentials in the
predicate.

## Why the build happens in GitHub Actions

A local SHA-256 hash alone does not establish GitHub's trusted build
provenance. The actual attestation is created in GitHub Actions using the
OIDC/Sigstore signing flow.

The workflow therefore builds the artifact and immediately attests the
resulting file.

## Project layout

```text
attestation-lab/
├── main.py
├── attestation_lab/
├── templates/
├── output/
└── README.md
```
