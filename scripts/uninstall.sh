#!/bin/bash
#
# Meridian Uninstaller
# Removes Axiom Meridian MCP server
#
# Usage:
#   bash scripts/uninstall.sh
#   DRY_RUN=1 bash scripts/uninstall.sh  # Show what would be removed
#

set -e

INSTALL_DIR="${INSTALL_DIR:-$HOME/.meridian}"
VENV_DIR="$INSTALL_DIR/venv"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

print_usage() {
    cat <<EOF
Meridian Uninstaller v1.2.0

Usage:
  bash scripts/uninstall.sh
  DRY_RUN=1 bash scripts/uninstall.sh  # Show what would be removed

Options:
  INSTALL_DIR=/path   Custom installation directory
  KNOWLEDGE_BASE_PATH=/path  Custom knowledge base path (for detection)
  DRY_RUN=1         Show what would be removed without executing

EOF
}

detect_mcp_clients() {
    log_step "Detecting MCP clients to clean..."

    CLIENTS_TO_CLEAN=()

    # Claude Code
    if command -v claude &> /dev/null; then
        if claude mcp list 2>/dev/null | grep -q '"meridian"' 2>/dev/null; then
            log_info "Found: Claude Code (meridian configured)"
            CLIENTS_TO_CLEAN+=("claude-code")
        fi
    fi

    # Kimi CLI
    if [ -f "$HOME/.kimi/mcp.json" ]; then
        if grep -q '"meridian"' "$HOME/.kimi/mcp.json" 2>/dev/null; then
            log_info "Found: Kimi CLI (meridian configured)"
            CLIENTS_TO_CLEAN+=("kimi-cli")
        fi
    fi

    # OpenCode
    if [ -f "$HOME/.config/opencode/opencode.json" ]; then
        if grep -q '"meridian"' "$HOME/.config/opencode/opencode.json" 2>/dev/null; then
            log_info "Found: OpenCode (meridian configured)"
            CLIENTS_TO_CLEAN+=("opencode")
        fi
    fi

    # VSCode
    if [ -f "$HOME/.config/Code/User/mcp.json" ]; then
        if grep -q '"meridian"' "$HOME/.config/Code/User/mcp.json" 2>/dev/null; then
            log_info "Found: VSCode (meridian configured)"
            CLIENTS_TO_CLEAN+=("vscode")
        fi
    fi

    if [ ${#CLIENTS_TO_CLEAN[@]} -eq 0 ]; then
        log_info "No MCP clients with meridian found."
    else
        log_info "Clients to clean: ${CLIENTS_TO_CLEAN[*]}"
    fi
}

confirm_uninstall() {
    log_warn "This will remove:"
    echo "  - $INSTALL_DIR"
    echo "  - MCP client configurations: ${CLIENTS_TO_CLEAN[*]:-none}"
    echo
    log_warn "The knowledge base will NOT be removed (your data is safe)."
    echo

    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would ask for confirmation"
        return
    fi

    read -p "Continue with uninstall? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Uninstall cancelled."
        exit 0
    fi
}

get_kb_path_from_env() {
    if [ -n "$KNOWLEDGE_BASE_PATH" ]; then
        echo "$KNOWLEDGE_BASE_PATH"
    elif [ -n "$HOME" ]; then
        if [ "$(uname)" = "Darwin" ]; then
            echo "$HOME/Library/Application Support/meridian"
        else
            echo "$HOME/.local/share/meridian"
        fi
    fi
}

remove_meridian_installation() {
    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would remove: $INSTALL_DIR"
        return
    fi

    log_info "Removing Meridian installation..."

    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        log_info "Removed $INSTALL_DIR"
    else
        log_info "Installation directory not found. Nothing to remove."
    fi
}

remove_claude_code() {
    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would remove from Claude Code"
        return
    fi

    log_info "Removing from Claude Code..."

    if command -v claude &> /dev/null; then
        if claude mcp list 2>/dev/null | grep -q '"meridian"' 2>/dev/null; then
            claude mcp remove meridian 2>/dev/null && log_info "Removed from Claude Code" || log_warn "Could not remove from Claude Code"
        else
            log_info "Meridian not configured in Claude Code"
        fi
    else
        log_info "Claude Code not found"
    fi
}

remove_kimi_cli() {
    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would remove from Kimi CLI"
        return
    fi

    log_info "Removing from Kimi CLI..."

    local kimi_config="$HOME/.kimi/mcp.json"

    if [ -f "$kimi_config" ]; then
        if grep -q '"meridian"' "$kimi_config" 2>/dev/null; then
            rm -f "$kimi_config"
            log_info "Removed from Kimi CLI"
        else
            log_info "Meridian not configured in Kimi CLI"
        fi
    else
        log_info "Kimi CLI config not found"
    fi
}

remove_opencode() {
    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would remove from OpenCode"
        return
    fi

    log_info "Removing from OpenCode..."

    local oc_config="$HOME/.config/opencode/opencode.json"

    if [ -f "$oc_config" ]; then
        if grep -q '"meridian"' "$oc_config" 2>/dev/null; then
            rm -f "$oc_config"
            log_info "Removed OpenCode config"
        else
            log_info "Meridian not configured in OpenCode"
        fi
    else
        log_info "OpenCode config not found"
    fi
}

remove_vscode() {
    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would remove from VSCode"
        return
    fi

    log_info "Removing from VSCode..."

    local vscode_config="$HOME/.config/Code/User/mcp.json"

    if [ -f "$vscode_config" ]; then
        if grep -q '"meridian"' "$vscode_config" 2>/dev/null; then
            rm -f "$vscode_config"
            log_info "Removed VSCode config"
        else
            log_info "Meridian not configured in VSCode"
        fi
    else
        log_info "VSCode config not found"
    fi
}

remove_mcp_configs() {
    log_step "Removing MCP client configurations..."

    for client in "${CLIENTS_TO_CLEAN[@]}"; do
        case "$client" in
            "claude-code")
                remove_claude_code
                ;;
            "kimi-cli")
                remove_kimi_cli
                ;;
            "opencode")
                remove_opencode
                ;;
            "vscode")
                remove_vscode
                ;;
        esac
    done

    if [ ${#CLIENTS_TO_CLEAN[@]} -eq 0 ]; then
        log_info "No MCP clients to clean."
    fi
}

print_summary() {
    local kb_path="${KNOWLEDGE_BASE_PATH:-$(get_kb_path_from_env)}"

    echo
    echo "════════════════════════════════════════════════"
    echo -e "  ${GREEN}Uninstall complete!${NC}"
    echo "══════════════════════════════════════��═════════"
    echo
    echo "Removed:"
    echo "  - $INSTALL_DIR"
    echo "  - MCP configs: ${CLIENTS_TO_CLEAN[*]:-none}"
    echo
    echo "Kept (your data):"
    echo "  - Knowledge base at: $kb_path"
    echo
    log_info "To reinstall, run:"
    echo "  bash scripts/install.sh"
    echo
}

main() {
    # Check for help flags
    for arg in "$@"; do
        case "$arg" in
            -h|--help|help)
                print_usage
                exit 0
                ;;
        esac
    done

    echo "════════════════════════════════════════════════"
    echo -e "  ${YELLOW}Meridian Uninstaller v1.2.0${NC}"
    echo "════════════════════════════════════════════════"
    echo

    export KNOWLEDGE_BASE_PATH="${KNOWLEDGE_BASE_PATH:-$(get_kb_path_from_env)}"

    log_info "Options:"
    echo "  Install directory:   $INSTALL_DIR"
    echo "  Knowledge base:     ${KNOWLEDGE_BASE_PATH:-auto}"
    echo "  Dry run:           ${DRY_RUN:-no}"
    echo

    detect_mcp_clients

    if [ "$DRY_RUN" = "1" ]; then
        log_warn "[DRY RUN] Would proceed with uninstallation"
        log_info "Would remove: $INSTALL_DIR"
        log_info "Would clean MCP clients: ${CLIENTS_TO_CLEAN[*]:-none}"
        confirm_uninstall
    else
        confirm_uninstall
    fi

    remove_meridian_installation
    remove_mcp_configs
    print_summary
}

main "$@"