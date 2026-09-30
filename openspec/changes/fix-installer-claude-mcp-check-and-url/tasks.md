## 1. Installer fixes

- [x] 1.1 `setup_claude_code()` (`scripts/install.sh`): replace
      `grep -q '"meridian"'` with `grep '^meridian:'` against `claude mcp
      list` output, capturing the matched line.
- [x] 1.2 When already configured, compare the captured line against
      `$BIN_DIR` (substring match, not the exact `$BIN_DIR/meridian`
      command) and print a mismatch warning with the exact
      `claude mcp remove`/`claude mcp add` remediation when it differs.
- [x] 1.3 `print_usage()`: fix the remote-install URL
      (`axiom-juma/meridian` → `abeljumanuel/axiom-meridian`) to match
      the correct one already in the file's top-of-file usage comment.

## 2. Verification

- [x] 2.1 Extract and run `setup_claude_code()` against the real
      `claude mcp list` output in an environment with Meridian already
      registered, with `$BIN_DIR` set to match the registration —
      confirm no mismatch warning and no attempted re-add.
- [x] 2.2 Same, with `$BIN_DIR` set to a different path — confirm the
      mismatch warning prints with accurate remediation commands.
- [x] 2.3 Same, with a fake `claude` that reports Meridian not
      registered — confirm it still proceeds to `claude mcp add`.
- [x] 2.4 Confirm the Kimi CLI/OpenCode/VSCode "already configured"
      checks (`grep -q '"meridian"' "$config_file"`) are unaffected —
      those grep real JSON files and are already correct.
