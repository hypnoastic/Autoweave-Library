# Testing & Quality Validation Matrix

This document outlines the testing philosophy, categories, tools, and quality validation thresholds for the AutoWeave Library.

## Testing Philosophy

AutoWeave Library is the core orchestration and durable execution engine behind AutoWeave. It is built to be a robust, dependency-safe, and highly tested package that can be confidently integrated into any production environment. 

We measure quality through a rigorous combination of automated test metrics, static analysis, coverage thresholds, and end-to-end package smoke testing.

## Testing Matrix

| Area          | What is tested                     | Tool                       | CI required      | Target                  |
| ------------- | ---------------------------------- | -------------------------- | ---------------- | ----------------------- |
| Unit          | Core exported logic & state models | `pytest`                   | Yes              | 80%+ coverage           |
| Integration   | Real library usage & DAG routing   | `pytest`                   | Yes              | Main flows pass         |
| Type Safety   | Public API types & generics        | `mypy`                     | Yes              | No type errors          |
| UI/Docs       | Navigation and dashboard behavior  | `pytest-playwright`        | Yes              | Main pages pass         |
| Security      | Dependencies, AST, and secrets     | `pip-audit`, `CodeQL`      | Yes              | No high/critical issues |
| Package       | Build, pack, install, import       | Custom smoke script        | Yes              | Package works           |

## Testing Categories Explained

### 1. Unit Tests
* **Focus**: Validation of individual functions, classes, and isolated runtime state transitions.
* **Metrics Tracked**: Total tests, core modules covered, invalid input handling, and error states.
* **Target**: Every public export in `autoweave/` must have at least one direct unit test. Edge cases and failure modes must be explicitly mocked and verified.

### 2. Integration Tests
* **Focus**: Simulating real developer usage scenarios, such as booting a local runtime, compiling a workflow, and executing it via Celery queues.
* **Metrics Tracked**: Full end-to-end routing behavior, multiple module interoperability, configuration overrides.
* **Target**: At least 3-5 realistic workflows simulated successfully.

### 3. Type Safety
* **Focus**: Preventing runtime TypeErrors through strict static analysis.
* **Metrics Tracked**: `mypy` strict mode passing on all source code.
* **Target**: Zero type errors across the `autoweave/` and `apps/` modules.

### 4. UI / Docs Tests
* **Focus**: Validating the local documentation playground and dashboard.
* **Metrics Tracked**: Headless browser rendering, sidebar navigation, dynamic UI components.
* **Target**: All main sections render properly; no broken links or empty states.

### 5. Security Validation
* **Focus**: Protecting the host system from supply chain attacks and insecure code patterns.
* **Metrics Tracked**: Continuous dependency auditing, secret scanning, and SAST.
* **Target**: No unsafe `eval()`, no insecure file operations, and no critical dependency CVEs.

### 6. Package Quality Validation
* **Focus**: Ensuring the `.whl` package works natively for consumers.
* **Metrics Tracked**: Build success, pure-Python wheel structure, installation into isolated virtualenv, and CLI smoke test success.
* **Target**: The library builds and executes cleanly without local repository context.

## Coverage Thresholds

We enforce the following hard limits in Continuous Integration:
* **Overall Line Coverage**: Minimum 80%
* **Function/Branch Coverage**: Strictly monitored to ensure robust logic validation.
* CI will deliberately fail if coverage drops below the 80% mark.

## Running Tests Locally

Use the bundled `Makefile` to execute quality checks natively:

```bash
# Run the full test suite
make test

# Run tests and generate coverage report
make test:coverage

# Run strictly UI tests
make test:ui

# Validate Python typing
make typecheck

# Run the package smoke test
make pack:check

# Run local security audits
make security:audit
```
