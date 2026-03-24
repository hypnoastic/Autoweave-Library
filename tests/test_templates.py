from __future__ import annotations

from autoweave.templates import sample_project


def test_sample_project_templates_define_real_skill_files() -> None:
    assert sample_project.AGENT_ROLES == ("manager", "backend", "frontend", "reviewer")

    for role in sample_project.AGENT_ROLES:
        skill_files = sample_project.AGENT_SKILL_FILES[role]
        assert skill_files[0].as_posix() == "skills/README.md"
        rendered = sample_project.render_agent_skill_files(role)

        assert set(rendered) == set(skill_files)
        assert "Use" in rendered[skill_files[0]]
        non_readme_files = [path for path in skill_files if path.name != "README.md"]
        assert non_readme_files
        for skill_path in non_readme_files:
            skill_text = rendered[skill_path]
            assert skill_text.startswith("# ")
            assert "## Do" in skill_text or "## When to use" in skill_text


def test_role_metadata_is_more_specific_than_placeholder_scaffold() -> None:
    manager = sample_project.render_agent_autoweave("manager")
    reviewer = sample_project.render_agent_autoweave("reviewer")

    assert "workflow-decomposition" in manager
    assert "workflow_decomposition" in manager
    assert "quality-and-release" in reviewer
    assert "qa_validation" in reviewer
