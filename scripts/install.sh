#!/bin/bash
set -e

VERSION="1.2.0"
MERIDIAN_REPO="https://github.com/abeljumanuel/axiom-meridian.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.meridian}"
KNOWLEDGE_BASE="${KNOWLEDGE_BASE:-auto}"
SKIP_MCP="${SKIP_MCP:-no}"
DRY_RUN="${DRY_RUN:-no}"
UNINSTALL="${UNINSTALL:-no}"

print_header() {
    echo "════════════════════════════════════════════════"
    echo "  Meridian Installer v${VERSION}"
    echo "════════════════════════════════════════════════"
}

log_info() {
    echo "[INFO] $1"
}

log_step() {
    echo "[STEP] $1"
}

log_error() {
    echo "[ERROR] $1"
}

log_warn() {
    echo "[WARN] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --install-dir)
                INSTALL_DIR="$2"
                shift 2
                ;;
            --knowledge-base)
                KNOWLEDGE_BASE="$2"
                shift 2
                ;;
            --skip-mcp)
                SKIP_MCP="yes"
                shift
                ;;
            --dry-run)
                DRY_RUN="yes"
                shift
                ;;
            --uninstall)
                UNINSTALL="yes"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
}

check_prerequisites() {
    log_step "Checking prerequisites..."

    if command -v python3 &>/dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        log_info "Python ${PYTHON_VERSION} found"
    else
        log_error "Python 3.11+ not found. Please install Python first."
        exit 1
    fi

    if ! command -v git &>/dev/null; then
        log_error "git not found. Please install git first."
        exit 1
    fi

    local os
    case "$(uname -s)" in
        Linux*) os="linux" ;;
        Darwin*) os="macos" ;;
        MINGW*|MSYS*|CYGWIN*) os="windows" ;;
        *) os="unknown" ;;
    esac
    log_info "Detected OS: ${os}"
}

detect_mcp_clients() {
    log_step "Detecting MCP clients..."

    local clients=()

    if command -v claude &>/dev/null; then
        clients+=("Claude Code")
        log_info "Found: Claude Code"
    fi

    if command -v kimi &>/dev/null; then
        clients+=("Kimi CLI")
        log_info "Found: Kimi CLI"
    fi

    if command -v opencode &>/dev/null; then
        clients+=("OpenCode")
        log_info "Found: OpenCode"
    fi

    if command -v code &>/dev/null || command -v code-insiders &>/dev/null || [[ -d "$HOME/.vscode" ]]; then
        clients+=("VSCode")
        log_info "Found: VSCode"
    fi

    log_info "Total clients found: ${#clients[@]}"
}

uninstall_meridian() {
    log_step "Uninstalling Meridian..."

    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_info "Installation directory not found. Nothing to uninstall."
        return
    fi

    if [[ "$DRY_RUN" == "yes" ]]; then
        log_info "[DRY RUN] Would remove: $INSTALL_DIR"
        return
    fi

    log_warn "This will remove Meridian and all its data."
    log_warn "The knowledge base at ~/meridian-kb will NOT be removed."

    read -p "Continue? [y/N] " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Uninstall cancelled."
        exit 0
    fi

    rm -rf "$INSTALL_DIR"
    log_success "Meridian uninstalled successfully."
    log_info "To remove your knowledge base, run:"
    log_info "  rm -rf ~/meridian-kb"
}

clone_repo() {
    log_step "Cloning Meridian repository..."

    if [[ "$DRY_RUN" == "yes" ]]; then
        log_info "[DRY RUN] Would clone $MERIDIAN_REPO to $INSTALL_DIR/repo"
        INSTALL_DIR="$HOME/.meridian"
        return
    fi

    local temp_dir="/tmp/meridian-install-$$"

    if [[ -d "$temp_dir" ]]; then
        rm -rf "$temp_dir"
    fi

    mkdir -p "$temp_dir"
    log_info "Cloning to temporary directory..."

    git clone --depth 1 "$MERIDIAN_REPO" "$temp_dir/repo"

    local repo_dir="$temp_dir/repo"

    if [[ ! -f "$repo_dir/pyproject.toml" ]]; then
        log_error "pyproject.toml not found in repository."
        rm -rf "$temp_dir"
        exit 1
    fi

    log_info "Repository cloned successfully"

    if [[ -d "$INSTALL_DIR/repo" ]]; then
        rm -rf "$INSTALL_DIR/repo"
    fi

    mkdir -p "$INSTALL_DIR"
    mv "$temp_dir/repo" "$INSTALL_DIR/repo"
    rm -rf "$temp_dir"

    log_info "Repository moved to $INSTALL_DIR/repo"
}

setup_install_dir() {
    log_step "Setting up installation directory..."

    if [[ -d "$INSTALL_DIR" ]]; then
        log_info "Installation directory already exists at $INSTALL_DIR"
    else
        mkdir -p "$INSTALL_DIR"
        log_info "Created installation directory at $INSTALL_DIR"
    fi
}

setup_venv() {
    log_step "Setting up Python virtual environment..."

    if [[ "$DRY_RUN" == "yes" ]]; then
        log_info "[DRY RUN] Would create venv at $INSTALL_DIR/venv"
        return
    fi

    local venv_path="$INSTALL_DIR/venv"

    if [[ -d "$venv_path" ]]; then
        log_info "Virtual environment already exists"
    else
        if ! python3 -m venv "$venv_path" 2>/dev/null; then
            log_error "Failed to create virtual environment."
            log_error "On Debian/Ubuntu, install python3-venv:"
            log_error "  sudo apt install python3-venv"
            log_error "On macOS, ensure Python was installed with homebrew or pyenv."
            exit 1
        fi
        log_info "Created virtual environment"
    fi

    log_info "Installing dependencies..."
    "$venv_path/bin/pip" install --upgrade pip wheel packaging
}

install_meridian() {
    log_step "Installing Meridian..."

    if [[ "$DRY_RUN" == "yes" ]]; then
        log_info "[DRY RUN] Would install meridian from $INSTALL_DIR/repo"
        return
    fi

    local venv_path="$INSTALL_DIR/venv"
    local repo_dir="$INSTALL_DIR/repo"

    "$venv_path/bin/pip" install -e "$repo_dir"
    log_info "Meridian installed successfully"
}

setup_knowledge_base() {
    if [[ "$KNOWLEDGE_BASE" == "auto" ]]; then
        return
    fi

    log_step "Setting up knowledge base..."

    local kb_path="${KNOWLEDGE_BASE:-$HOME/meridian-kb}"

    if [[ "$DRY_RUN" == "yes" ]]; then
        log_info "[DRY RUN] Would create knowledge base at $kb_path"
        return
    fi

    mkdir -p "$kb_path/knowledge-base/global"
    mkdir -p "$kb_path/knowledge-base/projects"
    mkdir -p "$kb_path/lessons/global"
    mkdir -p "$kb_path/lessons/projects"

    log_info "Knowledge base created at $kb_path"
    log_info "Set KNOWLEDGE_BASE_PATH=$kb_path"
}

main() {
    print_header
    parse_args "$@"

    if [[ "$UNINSTALL" == "yes" ]]; then
        check_prerequisites
        uninstall_meridian
        return
    fi

    echo ""
    log_info "Options:"
    log_info "  Install directory:  $INSTALL_DIR"
    log_info "  Knowledge base:    $KNOWLEDGE_BASE"
    log_info "  Skip MCP setup:     $SKIP_MCP"
    log_info "  Dry run:          $DRY_RUN"
    echo ""

    check_prerequisites
    detect_mcp_clients

    if [[ "$DRY_RUN" != "yes" ]]; then
        setup_install_dir
    fi

    clone_repo
    setup_venv
    install_meridian
    setup_knowledge_base

    echo ""
    log_success "Installation complete!"
    log_info ""
    log_info "Next steps:"
    log_info "  1. Add to your shell profile (~/.zshrc or ~/.bashrc):"
    log_info "     export KNOWLEDGE_BASE_PATH=\$HOME/meridian-kb"
    log_info ""
    log_info "  2. Restart your shell or run:"
    log_info "     source ~/.zshrc"
    log_info ""
    log_info "  3. Verify installation:"
    log_info "     $INSTALL_DIR/venv/bin/python -m meridian version"
    log_info ""
    log_info "To uninstall, run:"
    log_info "  INSTALL_DIR=$INSTALL_DIR bash -c 'curl -fsSL https://raw.githubusercontent.com/abeljumanuel/axiom-meridian/main/scripts/install.sh | bash -s -- --uninstall'"
}

main "$@"