"""Skill generator — creates SKILL.md + AGENTS.md for a project."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from meridian.tools.knowledge_consumption import query_rules


def generate_project_skills(
    conn: sqlite3.Connection,
    project_id: str,
    project_path: Path,
) -> dict[str, Path]:
    """Generate SKILL.md, references/rules.md and update AGENTS.md."""
    summary_json = query_rules(project_id, detail="summary", conn=conn)
    summary = json.loads(summary_json)

    full_json = query_rules(project_id, detail="full", conn=conn)
    full_rules = json.loads(full_json)

    skill_dir = project_path / ".claude" / "skills" / "meridian" / project_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    ref_dir = skill_dir / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)

    skill_md = _build_skill_md(project_id, summary)
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(skill_md, encoding="utf-8")

    rules_md = _build_rules_md(full_rules)
    rules_md_path = ref_dir / "rules.md"
    rules_md_path.write_text(rules_md, encoding="utf-8")

    agents_md_path = _update_agents_md(project_path, project_id)

    return {
        "skill_md": skill_md_path,
        "rules_md": rules_md_path,
        "agents_md": agents_md_path,
    }


def _build_skill_md(project_id: str, summary: list[dict]) -> str:
    lines = [
        "---",
        f"name: meridian-{project_id}",
        f"description: Knowledge audit rules for {project_id}",
        "metadata:",
        "  auto_invoke: true",
        "  allowed_tools:",
        "    - query_rules",
        "    - query_lessons",
        "    - get_rule_context",
        "    - get_rule_timeline",
        "    - audit_pr",
        "    - analyze_pr_feedback",
        "    - check_feature_against_rules",
        "---",
        "",
        "## Rules Summary",
        "",
        "| Code | Scope | Severity | Category |",
        "|------|-------|----------|----------|",
    ]
    for rule in summary:
        code = rule.get("code", "")
        scope = rule.get("scope_id", "")
        severity = rule.get("severity", "")
        category = rule.get("category", "")
        lines.append(f"| {code} | {scope} | {severity} | {category} |")

    lines.extend([
        "",
        "## Full Rules",
        "",
        "See [references/rules.md](references/rules.md) for complete rule text.",
        "",
    ])
    return "\n".join(lines)


def _build_rules_md(full_rules: list[dict]) -> str:
    parts: list[str] = []
    for rule in full_rules:
        code = rule.get("code", rule.get("id", ""))
        text = rule.get("text", "")
        parts.append(f"## {code}\n")
        parts.append(text or "")
        parts.append("")
    return "\n".join(parts)


def _update_agents_md(project_path: Path, project_id: str) -> Path:
    agents_path = project_path / "AGENTS.md"
    section_header = "## Auto-invoke Skills (Meridian)"
    section_body = (
        "| Action | Skill |\n"
        "|--------|-------|\n"
        f"| Implementing any new feature | `meridian-{project_id}` |\n"
        f"| Before submitting a PR | `meridian-{project_id}` |\n"
        f"| Receiving Tech Lead feedback | `meridian-{project_id}` |"
    )
    section = f"{section_header}\n{section_body}"

    if agents_path.exists():
        content = agents_path.read_text(encoding="utf-8")
        if section_header in content:
            before, _, after = content.partition(section_header)
            before = before.rstrip()
            next_section = after.find("\n## ")
            if next_section != -1:
                after = after[next_section:].lstrip()
            else:
                after = ""
            if before:
                content = f"{before}\n\n{section}\n\n{after}".strip() + "\n"
            else:
                content = f"{section}\n\n{after}".strip() + "\n"
        else:
            content = content.rstrip() + "\n\n" + section + "\n"
    else:
        content = section + "\n"

    agents_path.write_text(content, encoding="utf-8")
    return agents_path
