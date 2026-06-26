# Contributing to AutoWeave

Thank you for your interest in contributing to AutoWeave! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Commit Conventions](#commit-conventions)
- [Branching Strategy](#branching-strategy)
- [Pull Request Process](#pull-request-process)
- [Review Checklist](#review-checklist)
- [Reporting Issues](#reporting-issues)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.

---

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Autoweave.git
   cd Autoweave
   ```
3. **Add upstream** remote:
   ```bash
   git remote add upstream https://github.com/hypnoastic/Autoweave.git
   ```
4. **Set up** your development environment (see below)

---

## Development Setup

### Prerequisites

- Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/) (recommended package manager)
- Docker & Docker Compose (for integration testing)
- Git

### Installation

```bash
# Install in development mode with all dev dependencies
uv pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Copy environment template
cp .env.example .env.local
# Edit .env.local with your local configuration
```

### Verify Setup

```bash
# Run linting
make lint

# Run type checking
make typecheck

# Run tests
make test

# Run all checks
make check
```

> 📖 See [DEVELOPMENT.md](DEVELOPMENT.md) for the complete development guide including Docker setup, environment variables, and troubleshooting.

---

## Coding Standards

### Python Style

- **Formatter**: [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`)
- **Line length**: 120 characters
- **Quotes**: Double quotes
- **Import sorting**: isort-compatible via Ruff

### Type Annotations

- All new public functions must include type annotations
- Use `from __future__ import annotations` for forward references
- Run `make typecheck` to validate with mypy

### Docstrings

- Use triple-double-quote docstrings for all public modules, classes, and functions
- Follow the existing pattern in the codebase (concise one-liners for simple functions, multi-line for complex ones)

### Code Organization

- Domain models go in `autoweave/models.py`
- Each subsystem has its own subpackage under `autoweave/`
- Public API surface is defined in `autoweave/__init__.py`
- CLI commands go in `apps/cli/`
- Tests mirror the source structure in `tests/`

### Pre-commit Hooks

Pre-commit hooks run automatically on `git commit`. They enforce:

- Ruff linting and formatting
- YAML/TOML validation
- Trailing whitespace removal
- Merge conflict detection

To run manually:

```bash
pre-commit run --all-files
```

---

## Commit Conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/). Each commit should change **one coherent concern**.

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

| Type | When to use |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `docs` | Documentation only changes |
| `chore` | Maintenance (CI, deps, tooling) |
| `perf` | Performance improvement |

### Scopes

Use the subsystem name: `runtime`, `monitoring`, `storage`, `cli`, `queue`, `ci`, `docs`

### Examples

```
feat(runtime): add workflow retry with exponential backoff
fix(queue): handle Redis connection timeout gracefully
test(runtime): add coverage for edge state transitions
docs(runtime): document durable execution guarantees
chore(ci): add Python 3.12 to test matrix
```

### What NOT to commit

- `.pytest_cache/`, `__pycache__/`
- Virtual environment files
- `var/` runtime state
- Temporary workspaces
- Secrets or credentials
- Ad hoc debug files

---

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, release-ready code |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `chore/<name>` | Maintenance tasks |
| `docs/<name>` | Documentation updates |

Always branch from `main`:

```bash
git checkout main
git pull upstream main
git checkout -b feat/my-feature
```

---

## Pull Request Process

1. **Create a branch** following the branching strategy above
2. **Make your changes** in small, focused commits
3. **Run all checks** locally:
   ```bash
   make check
   ```
4. **Push** your branch and open a PR against `main`
5. **Fill out** the PR template completely
6. **Wait for CI** to pass — all checks must be green
7. **Address review feedback** with additional commits (do not force-push during review)
8. **Squash and merge** is the preferred merge strategy

### PR Requirements

- [ ] All CI checks pass
- [ ] Code follows the coding standards
- [ ] Tests added/updated for changed behavior
- [ ] Documentation updated if public API changed
- [ ] No unrelated changes bundled in

---

## Review Checklist

Reviewers should verify:

- [ ] **Correctness**: Does the change do what it claims?
- [ ] **Tests**: Are there adequate tests for new behavior?
- [ ] **Types**: Are type annotations present and correct?
- [ ] **Documentation**: Are public APIs documented?
- [ ] **Security**: No hardcoded secrets, no unsafe patterns
- [ ] **Performance**: No obvious performance regressions
- [ ] **Compatibility**: Does this break existing public API?
- [ ] **Scope**: Is the PR focused on one concern?

---

## Reporting Issues

### Bug Reports

Use the [Bug Report template](https://github.com/hypnoastic/Autoweave/issues/new?template=bug_report.yml) and include:

- Steps to reproduce
- Expected vs actual behavior
- Python version and OS
- Relevant logs or error messages

### Feature Requests

Use the [Feature Request template](https://github.com/hypnoastic/Autoweave/issues/new?template=feature_request.yml) and include:

- Problem description
- Proposed solution
- Alternative approaches considered

### Security Vulnerabilities

**Do NOT open a public issue.** See our [Security Policy](SECURITY.md) for responsible disclosure.

---

## Questions?

If you have questions about contributing, open a [Discussion](https://github.com/hypnoastic/Autoweave/discussions) or reach out to the maintainers.

Thank you for helping make AutoWeave better! 🎉
