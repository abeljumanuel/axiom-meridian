"""Entry point for `python -m meridian`."""

import json
import sys

_USAGE = "Usage: python -m meridian [mcp|serve|version|db|migrate|index|proposals|query]"


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _get_flag(argv: list[str], name: str) -> str | None:
    """Return the value following a `--flag` in argv, or None if absent."""
    if name in argv:
        idx = argv.index(name)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def _check_python_environment() -> None:
    """Verify that the Python interpreter can import critical dependencies."""
    try:
        import sqlite3  # noqa: F401
        import fastmcp  # noqa: F401
    except ImportError as exc:
        print(
            f"ERROR: Incomplete Python environment — {exc}",
            file=sys.stderr,
        )
        print("Run: uv sync", file=sys.stderr)
        sys.exit(1)


def _cmd_version(argv: list[str]) -> None:
    from meridian import __version__

    print(f"Axiom Meridian v{__version__}")


def _cmd_mcp(argv: list[str]) -> None:
    _check_python_environment()
    from meridian.server import run_stdio

    run_stdio()


def _cmd_serve(argv: list[str]) -> None:
    from meridian.server import run_http

    port = int(argv[2]) if len(argv) > 2 else 8080
    run_http(port)


def _cmd_db(argv: list[str]) -> None:
    if len(argv) < 3 or argv[2] != "init":
        print("Usage: python -m meridian db init")
        sys.exit(1)
    from meridian.config import get_db_path
    from meridian.db.connection import initialize_db

    db_path = get_db_path()
    initialize_db(db_path)
    print(f"Database initialized at {db_path}")


def _cmd_migrate(argv: list[str]) -> None:
    usage = "Usage: python -m meridian migrate <rules|lessons> <file> --scope <scope_id>"
    if len(argv) < 5 or argv[4] != "--scope" or len(argv) < 6:
        print(usage)
        sys.exit(1)

    doc_type, filepath, scope_id = argv[2], argv[3], argv[5]
    from meridian.tools.knowledge_management import convert_to_atomic_format

    _print_json(convert_to_atomic_format(filepath, scope_id, doc_type))


def _cmd_index(argv: list[str]) -> None:
    usage = "Usage: python -m meridian index <rules|lessons> <file> --scope <scope_id>"
    if len(argv) < 5 or argv[4] != "--scope" or len(argv) < 6:
        print(usage)
        sys.exit(1)

    doc_type, filepath, scope_id = argv[2], argv[3], argv[5]
    from meridian.config import get_db_path
    from meridian.db.connection import initialize_db

    initialize_db(get_db_path())

    if doc_type == "rules":
        from meridian.tools.knowledge_management import index_rules_from_markdown

        result = index_rules_from_markdown(filepath, default_scope_id=scope_id, mode="atomic")
    elif doc_type == "lessons":
        from meridian.tools.knowledge_management import index_lessons_from_markdown

        result = index_lessons_from_markdown(filepath, default_scope_id=scope_id, mode="atomic")
    else:
        print(f"Unknown index doc_type: {doc_type}. Use 'rules' or 'lessons'.")
        sys.exit(1)
    _print_json(result)


def _cmd_proposals_list(argv: list[str]) -> None:
    from meridian.tools.knowledge_management import list_pending_proposals

    _print_json(list_pending_proposals(status=_get_flag(argv, "--status")))


def _cmd_proposals_approve(argv: list[str]) -> None:
    if len(argv) < 4:
        print("Usage: python -m meridian proposals approve <id>")
        sys.exit(1)
    from meridian.tools.knowledge_management import approve_proposal

    _print_json(approve_proposal(argv[3]))


def _cmd_proposals(argv: list[str]) -> None:
    if len(argv) < 3:
        print("Usage: python -m meridian proposals [list|approve]")
        sys.exit(1)

    subcommand = argv[2]
    if subcommand == "list":
        _cmd_proposals_list(argv)
    elif subcommand == "approve":
        _cmd_proposals_approve(argv)
    else:
        print(f"Unknown proposals subcommand: {subcommand}")
        sys.exit(1)


def _cmd_query_rules(argv: list[str]) -> None:
    project_id = _get_flag(argv, "--project")
    if project_id is None:
        print("Usage: python -m meridian query rules --project <project_id>")
        sys.exit(1)
    from meridian.tools.knowledge_consumption import query_rules

    print(
        query_rules(
            project_id=project_id,
            category=_get_flag(argv, "--category"),
            severity=_get_flag(argv, "--severity"),
        )
    )


def _cmd_query_lessons(argv: list[str]) -> None:
    project_id = _get_flag(argv, "--project")
    if project_id is None:
        print("Usage: python -m meridian query lessons --project <project_id>")
        sys.exit(1)
    from meridian.tools.knowledge_consumption import query_lessons

    print(query_lessons(project_id=project_id, area=_get_flag(argv, "--area")))


def _cmd_query(argv: list[str]) -> None:
    if len(argv) < 3:
        print("Usage: python -m meridian query [rules|lessons]")
        sys.exit(1)

    subcommand = argv[2]
    if subcommand == "rules":
        _cmd_query_rules(argv)
    elif subcommand == "lessons":
        _cmd_query_lessons(argv)
    else:
        print(f"Unknown query subcommand: {subcommand}")
        sys.exit(1)


_COMMANDS = {
    "version": _cmd_version,
    "mcp": _cmd_mcp,
    "serve": _cmd_serve,
    "db": _cmd_db,
    "migrate": _cmd_migrate,
    "index": _cmd_index,
    "proposals": _cmd_proposals,
    "query": _cmd_query,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(_USAGE)
        sys.exit(1)

    handler = _COMMANDS.get(sys.argv[1])
    if handler is None:
        print(f"Unknown command: {sys.argv[1]}")
        print(_USAGE)
        sys.exit(1)

    handler(sys.argv)


if __name__ == "__main__":
    main()
