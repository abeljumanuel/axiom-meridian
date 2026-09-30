## 1. Installer fix

- [x] 1.1 In `seed_knowledge_base()`'s file loop (`scripts/install.sh`),
      check `[ -e "$dest" ]` before the `cp "$f" "$dest"` call; if it
      exists, `log_warn` naming the file and reason, `continue` (skip
      both the copy and the subsequent `meridian index` call for it).

## 2. Verification

- [x] 2.1 Reproduce the bug against a throwaway `KNOWLEDGE_BASE_PATH`
      with a pre-existing `knowledge-base/global/java.md` containing
      known content; run `SEED_KB=1 bash scripts/install.sh`; confirm
      (pre-fix) the file gets overwritten with the bundled sample.
- [x] 2.2 Re-run the same repro against the fixed script; confirm the
      pre-existing file's bytes are unchanged and a skip warning was
      logged naming it.
- [x] 2.3 Confirm a fresh (empty) `KNOWLEDGE_BASE_PATH` still seeds and
      indexes every bundled example file exactly as before — no
      regression on the common case.
