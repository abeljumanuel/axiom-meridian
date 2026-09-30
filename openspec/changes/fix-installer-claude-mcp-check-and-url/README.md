# fix-installer-claude-mcp-check-and-url

setup_claude_code's already-configured check greps claude mcp list output for a quoted substring that never appears, always falling through to a failing re-add; the remote-install URL in print_usage also points at a nonexistent repo
