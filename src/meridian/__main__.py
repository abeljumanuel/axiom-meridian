"""Entry point for `python -m meridian`."""

import json
import sys


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


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


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m meridian [mcp|serve|version|db|migrate|proposals|query]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "version":
        from meridian import __version__
        print(f"Axiom Meridian v{__version__}")

    elif command == "mcp":
        _check_python_environment()
        from meridian.server import run_stdio
        run_stdio()

    elif command == "serve":
        from meridian.server import run_http
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
        run_http(port)

    elif command == "db":
        if len(sys.argv) < 3 or sys.argv[2] != "init":
            print("Usage: python -m meridian db init")
            sys.exit(1)
        from meridian.config import get_db_path
        from meridian.db.connection import initialize_db
        db_path = get_db_path()
        initialize_db(db_path)
        print(f"Database initialized at {db_path}")

    elif command == "migrate":
        if len(sys.argv) < 5:
            print("Usage: python -m meridian migrate <rules|lessons> <file> --scope <scope_id>")
            sys.exit(1)
        doc_type = sys.argv[2]
        filepath = sys.argv[3]
        if sys.argv[4] != "--scope" or len(sys.argv) < 6:
            print("Usage: python -m meridian migrate <rules|lessons> <file> --scope <scope_id>")
            sys.exit(1)
        scope_id = sys.argv[5]
        from meridian.tools.knowledge_management import convert_to_atomic_format
        result = convert_to_atomic_format(filepath, scope_id, doc_type)
        _print_json(result)

    elif command == "proposals":
        if len(sys.argv) < 3:
            print("Usage: python -m meridian proposals [list|approve]")
            sys.exit(1)
        subcommand = sys.argv[2]
        if subcommand == "list":
            status = None
            if "--status" in sys.argv:
                idx = sys.argv.index("--status")
                if idx + 1 < len(sys.argv):
                    status = sys.argv[idx + 1]
            from meridian.tools.knowledge_management import list_pending_proposals
            proposals = list_pending_proposals(status=status)
            _print_json(proposals)
        elif subcommand == "approve":
            if len(sys.argv) < 4:
                print("Usage: python -m meridian proposals approve <id>")
                sys.exit(1)
            proposal_id = sys.argv[3]
            from meridian.tools.knowledge_management import approve_proposal
            result = approve_proposal(proposal_id)
            _print_json(result)
        else:
            print(f"Unknown proposals subcommand: {subcommand}")
            sys.exit(1)

    elif command == "query":
        if len(sys.argv) < 3:
            print("Usage: python -m meridian query [rules|lessons]")
            sys.exit(1)
        subcommand = sys.argv[2]
        if subcommand == "rules":
            project_id = None
            category = None
            severity = None
            if "--project" in sys.argv:
                idx = sys.argv.index("--project")
                if idx + 1 < len(sys.argv):
                    project_id = sys.argv[idx + 1]
            if "--category" in sys.argv:
                idx = sys.argv.index("--category")
                if idx + 1 < len(sys.argv):
                    category = sys.argv[idx + 1]
            if "--severity" in sys.argv:
                idx = sys.argv.index("--severity")
                if idx + 1 < len(sys.argv):
                    severity = sys.argv[idx + 1]
            if project_id is None:
                print("Usage: python -m meridian query rules --project <project_id>")
                sys.exit(1)
            from meridian.tools.knowledge_consumption import query_rules
            result = query_rules(
                project_id=project_id,
                category=category,
                severity=severity,
            )
            print(result)
        elif subcommand == "lessons":
            project_id = None
            area = None
            if "--project" in sys.argv:
                idx = sys.argv.index("--project")
                if idx + 1 < len(sys.argv):
                    project_id = sys.argv[idx + 1]
            if "--area" in sys.argv:
                idx = sys.argv.index("--area")
                if idx + 1 < len(sys.argv):
                    area = sys.argv[idx + 1]
            if project_id is None:
                print("Usage: python -m meridian query lessons --project <project_id>")
                sys.exit(1)
            from meridian.tools.knowledge_consumption import query_lessons
            result = query_lessons(
                project_id=project_id,
                area=area,
            )
            print(result)
        else:
            print(f"Unknown query subcommand: {subcommand}")
            sys.exit(1)

    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m meridian [mcp|serve|version|db|migrate|proposals|query]")
        sys.exit(1)


if __name__ == "__main__":
    main()
