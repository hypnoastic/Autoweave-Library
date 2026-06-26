#!/usr/bin/env python3
"""
AutoWeave Project Health Reporter

This script evaluates the repository against open-source best practices and generates
a comprehensive health score and report.
"""

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]


def check_file_exists(filename: str) -> bool:
    return (ROOT_DIR / filename).exists()


def evaluate_documentation() -> dict[str, Any]:
    checks = {
        "README.md": check_file_exists("README.md"),
        "CONTRIBUTING.md": check_file_exists("CONTRIBUTING.md"),
        "LICENSE": check_file_exists("LICENSE"),
        "SECURITY.md": check_file_exists("SECURITY.md"),
        "CODE_OF_CONDUCT.md": check_file_exists("CODE_OF_CONDUCT.md"),
        "Architecture Doc": check_file_exists("docs/ARCHITECTURE.md"),
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return {"score": score, "checks": checks}


def evaluate_community() -> dict[str, Any]:
    checks = {
        "Bug Report Template": check_file_exists(".github/ISSUE_TEMPLATE/bug_report.yml"),
        "Feature Request Template": check_file_exists(".github/ISSUE_TEMPLATE/feature_request.yml"),
        "PR Template": check_file_exists(".github/PULL_REQUEST_TEMPLATE.md"),
        "CODEOWNERS": check_file_exists(".github/CODEOWNERS"),
        "Dependabot": check_file_exists(".github/dependabot.yml"),
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return {"score": score, "checks": checks}


def evaluate_tooling() -> dict[str, Any]:
    checks = {
        "Pre-commit Config": check_file_exists(".pre-commit-config.yaml"),
        "EditorConfig": check_file_exists(".editorconfig"),
        "Pyproject Configuration": check_file_exists("pyproject.toml"),
        "Makefile": check_file_exists("Makefile"),
        "Python Version Pinned": check_file_exists(".python-version"),
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return {"score": score, "checks": checks}


def generate_markdown_report(data: dict[str, Any]) -> str:
    md = [
        "# AutoWeave Project Health Report",
        "",
        f"**Overall Health Score: {data['overall_score']:.0f}%**",
        "",
        "## Category Breakdown",
        "",
        f"- **Documentation:** {data['documentation']['score'] * 100:.0f}%",
        f"- **Community Standards:** {data['community']['score'] * 100:.0f}%",
        f"- **Development Tooling:** {data['tooling']['score'] * 100:.0f}%",
        "",
        "## Detailed Results",
        "",
    ]

    for category_name, category_data in [
        ("Documentation", data["documentation"]),
        ("Community Standards", data["community"]),
        ("Development Tooling", data["tooling"]),
    ]:
        md.append(f"### {category_name}")
        for check, passed in category_data["checks"].items():
            icon = "✅" if passed else "❌"
            md.append(f"- {icon} {check}")
        md.append("")

    return "\n".join(md)


def main() -> None:
    print("Evaluating project health...")

    doc_results = evaluate_documentation()
    community_results = evaluate_community()
    tooling_results = evaluate_tooling()

    overall_score = (doc_results["score"] + community_results["score"] + tooling_results["score"]) / 3 * 100

    report_data = {
        "overall_score": overall_score,
        "documentation": doc_results,
        "community": community_results,
        "tooling": tooling_results,
    }

    # Ensure reports directory exists
    reports_dir = ROOT_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    # Write JSON
    with open(reports_dir / "health_report.json", "w") as f:
        json.dump(report_data, f, indent=2)

    # Write Markdown
    md_content = generate_markdown_report(report_data)
    with open(reports_dir / "health_report.md", "w") as f:
        f.write(md_content)

    print(f"Health check complete! Overall Score: {overall_score:.0f}%")
    print("Reports generated in reports/ directory.")

    # Fail CI if health is too low
    if overall_score < 80:
        print("\nERROR: Project health is below 80% threshold.")
        exit(1)


if __name__ == "__main__":
    main()
