## 1. Installer fix

- [x] 1.1 Change the bare `return` in `setup_venv()`'s declined-recreate
      branch (`scripts/install.sh`, the `else` of
      `if [[ $REPLY =~ ^[Yy]$ ]]`) to `return 0`.

## 2. Verification

- [x] 2.1 Reproduce the bug in isolation (a minimal `set -e` + function +
      bare `return` in a false-condition `else` branch) and confirm the
      script aborts before the fix.
- [x] 2.2 Re-run the same isolated repro with `return 0` and confirm
      execution continues past the function call.
- [x] 2.3 Confirm no other bare `return` in `install.sh`/`uninstall.sh`
      shares the bug (audit: all 18 remaining occurrences sit in `then`
      branches of conditions that evaluated true, or after a command
      like `log_info` that itself returns 0).
