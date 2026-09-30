## ADDED Requirements

### Requirement: Declining to recreate an existing venv does not abort the installer
When `scripts/install.sh`'s `setup_venv()` finds an existing virtual environment at `$VENV_DIR` and the user answers anything other than `y`/`Y` to "Recreate it? [y/N]", the function SHALL return a zero (success) exit status and the installer SHALL continue with the remaining setup steps using the existing venv, instead of `set -e` terminating the script.

#### Scenario: User declines to recreate an existing venv
- **WHEN** `$VENV_DIR` already exists and the user answers `N` (or presses Enter, the default) to "Recreate it? [y/N]"
- **THEN** `setup_venv` returns exit status 0 and `install.sh` proceeds to `install_meridian` and the remaining steps

#### Scenario: User confirms recreating an existing venv
- **WHEN** `$VENV_DIR` already exists and the user answers `Y` to "Recreate it? [y/N]"
- **THEN** the existing `$VENV_DIR` is removed and a fresh venv is created, unchanged from prior behavior
