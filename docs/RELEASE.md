# Release Process

This document outlines the steps for releasing a new version of the AutoWeave Library.

The release process is largely automated via GitHub Actions (`.github/workflows/release.yml`), triggered by Git tags.

## Pre-Release Checklist

Before creating a release, ensure:

1. **Tests pass**: `make check` is fully green on the `main` branch.
2. **Version Bump**: The version string in `pyproject.toml` is updated to the target release version.
3. **Changelog**: The `CHANGELOG.md` (if applicable) is updated with the latest changes.
4. **Smoke Test**: `make pack:check` succeeds locally, confirming the wheel builds and installs correctly.

## Creating a Release

Releases are triggered by pushing a semver tag (e.g., `v0.1.1`).

### 1. Tag the Release

Create an annotated tag pointing to the commit you want to release:

```bash
git tag -a v0.1.1 -m "Release v0.1.1"
```

### 2. Push the Tag

Push the tag to the remote repository. This will trigger the `Release` GitHub Action workflow.

```bash
git push origin v0.1.1
```

### 3. Automated Workflow Execution

The `Release` workflow will perform the following steps:
- Checkout the repository.
- Build the source distribution (`.tar.gz`) and wheel (`.whl`) via the custom `build_backend.py`.
- Run the smoke test against the newly built wheel.
- Publish the artifacts to PyPI (requires proper PyPI token configuration in GitHub Secrets).
- Create a GitHub Release with an auto-generated changelog and attach the wheel asset.

## Post-Release

1. Verify the release appears correctly on PyPI: `https://pypi.org/project/autoweave/`
2. Verify the GitHub Release was created and contains the release notes.
3. Announce the release to the team/community.
