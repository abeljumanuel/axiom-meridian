# fix-installer-setup-venv-abort-on-decline

setup_venv's bare 'return' in the declined-recreate branch inherits the failed [[ ]] test's exit code (1), so set -e aborts install.sh right after answering N to 'Recreate it?'
