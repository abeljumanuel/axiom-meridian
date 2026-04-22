#!/bin/bash
#
# Meridian Installer
# Installs Axiom Meridian MCP server
#
# Usage:
#   Local:     bash scripts/install.sh
#   Remote:    curl -fsSL https://raw.githubusercontent.com/abeljumanuel/axiom-meridian/main/scripts/install.sh | bash
#
# Options:
#   INSTALL_DIR=/path/to/install   - Custom installation directory (default: ~/.meridian)
#   KNOWLEDGE_BASE_PATH=/path    - Custom knowledge base path
#   SKIP_MCP=1                    - Skip MCP client configuration
#   DRY_RUN=1                     - Show what would be done without executing
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.meridian}"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$VENV_DIR/bin"

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

check_prerequisites() {
    log_step "Checking prerequisites..."

    if ! command -v python3 &> /dev/null; then
        log_error "Python 3.11+ is required but not found."
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
        log_error "Python 3.11+ is required. Found: $PYTHON_VERSION"
        exit 1
    fi

    log_info "Python $PYTHON_VERSION found"
}

check_network() {
    if [ "$DRY_RUN" = "1" ]; then
        log_info "[DRY RUN] Would check network connectivity"
        return
    fi

    if command -v curl &> /dev/null; then
        if ! curl -fsSL --max-time 5 https://github.com >/dev/null 2>&1; then
            log_warn "No network connectivity. Local installation may fail."
        fi
    elif command -v wget &> /dev/null; then
        if ! wget --max-time=5 -q -O - https://github.com >/dev/null 2>&1; then
            log_warn "No network connectivity. Local installation may fail."
        fi
    fi
}

detect_os() {
    if [ "$(uname)" = "Darwin" ]; then
        OS="macos"
    elif [ "$(uname)" = "Linux" ]; then
        OS="linux"
    else
        log_error "Unsupported operating system"
        exit 1
    fi
    log_info "Detected OS: $OS"
}

get_default_kb_path() {
    if [ "$OS" = "macos" ]; then
        echo "$HOME/Library/Application Support/meridian"
    else
        echo "$HOME/.local/share/meridian"
    fi
}

detect_mcp_clients() {
    log_step "Detecting MCP clients..."

    CLIENTS_FOUND=()

    # Claude Code
    if command -v claude &> /dev/null; then
        log_info "Found: Claude Code"
        CLIENTS_FOUND+=("claude-code")
    fi

    # Kimi CLI
    if command -v kimi &> /dev/null; then
        log_info "Found: Kimi CLI"
        CLIENTS_FOUND+=("kimi-cli")
    fi

    # OpenCode
    if command -v opencode &> /dev/null; then
        log_info "Found: OpenCode"
        CLIENTS_FOUND+=("opencode")
    fi

    # VSCode
    if [ -d "$HOME/.vscode" ] || [ -d "$HOME/.config/Code" ]; then
        log_info "Found: VSCode"
        CLIENTS_FOUND+=("vscode")
    fi

    if [ ${#CLIENTS_FOUND[@]} -eq 0 ]; then
        log_warn "No MCP clients detected. Install one to use Meridian."
    else
        log_info "Total clients found: ${#CLIENTS_FOUND[@]}"
    fi
}

create_install_dir() {
    log_info "Creating installation directory at $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
}

setup_venv() {
    log_info "Setting up Python virtual environment..."

    if [ -d "$VENV_DIR" ]; then
        log_warn "Virtual environment already exists at $VENV_DIR"
        read -p "Recreate it? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$VENV_DIR"
            python3 -m venv "$VENV_DIR"
        fi
    else
        python3 -m venv "$VENV_DIR"
    fi

    log_info "Installing dependencies..."
    "$BIN_DIR/pip" install --upgrade pip wheel
}

install_meridian() {
    log_info "Installing Meridian..."

    cd "$SCRIPT_DIR"

    if [ -f "pyproject.toml" ]; then
        "$BIN_DIR/pip" install -e .
    else
        log_error "pyproject.toml not found. Run from Meridian repository."
        exit 1
    fi
}

create_knowledge_base() {
    KB_PATH="${KNOWLEDGE_BASE_PATH:-$(get_default_kb_path)}"

    log_info "Creating knowledge base at $KB_PATH"

    mkdir -p "$KB_PATH/knowledge-base/global"
    mkdir -p "$KB_PATH/knowledge-base/projects"
    mkdir -p "$KB_PATH/lessons/global"
    mkdir -p "$KB_PATH/lessons/projects"

    touch "$KB_PATH/meridian.db"

    export KNOWLEDGE_BASE_PATH="$KB_PATH"
}

setup_claude_code() {
    log_info "Setting up Claude Code..."

    local config_exists=false
    local mcp_entry=""

    if [ -f "$HOME/.claude.json" ]; then
        config_exists=true
    fi

    # Check if already configured
    if claude mcp list 2>/dev/null | grep -q '"meridian"'; then
        log_warn "Meridian already configured in Claude Code. Skipping."
        return
    fi

    # Add to Claude Code
    if claude mcp add -s user \
        -e KNOWLEDGE_BASE_PATH="$KNOWLEDGE_BASE_PATH" \
        -e MERIDIAN_ACCESS_LEVEL=write \
        -- meridian \
        "$BIN_DIR/python" \
        -m meridian mcp 2>/dev/null; then
        log_info "Added to Claude Code"
    else
        log_warn "Could not add to Claude Code. Add manually:"
        mcp_entry="  claude mcp add -s user -e KNOWLEDGE_BASE_PATH=\"$KNOWLEDGE_BASE_PATH\" -e MERIDIAN_ACCESS_LEVEL=write -- meridian \"$BIN_DIR/python\" -m meridian mcp"
    fi
}

setup_kimi_cli() {
    log_info "Setting up Kimi CLI..."

    local kimi_config_dir="$HOME/.kimi"
    local kimi_config="$kimi_config_dir/mcp.json"

    mkdir -p "$kimi_config_dir"

    if [ -f "$kimi_config" ]; then
        if grep -q '"meridian"' "$kimi_config" 2>/dev/null; then
            log_warn "Meridian already configured in Kimi CLI. Skipping."
            return
        fi
    fi

    # Create or update config
    local meridan_config=$(cat <<EOF
{
  "mcpServers": {
    "meridian": {
      "command": "$BIN_DIR/python",
      "args": ["-m", "meridian", "mcp"],
      "env": {
        "KNOWLEDGE_BASE_PATH": "$KNOWLEDGE_BASE_PATH",
        "MERIDIAN_ACCESS_LEVEL": "write"
      }
    }
  }
}
EOF
)

    if [ -f "$kimi_config" ]; then
        # Merge configs (simple approach - just log warning)
        log_warn "Kimi CLI config exists. Add manually:"
        log_warn "$meridan_config"
    else
        echo "$meridan_config" > "$kimi_config"
        log_info "Created Kimi CLI config at $kimi_config"
    fi
}

setup_opencode() {
    log_info "Setting up OpenCode..."

    local oc_config_dir="$HOME/.config/opencode"
    local oc_config="$oc_config_dir/opencode.json"

    mkdir -p "$oc_config_dir"

    local meridian_config=$(cat <<'EOF'
{
  "mcp": {
    "meridian": {
      "type": "local",
      "command": ["REPLACE_BIN_PATH", "-m", "meridian", "mcp"],
      "env": {
        "KNOWLEDGE_BASE_PATH": "REPLACE_KB_PATH",
        "MERIDIAN_ACCESS_LEVEL": "write"
      }
    }
  },
  "permission": {
    "mcp": {
      "meridian": "ask"
    }
  }
}
EOF
)

    # Replace placeholders
    meridian_config="${meridian_config//REPLACE_BIN_PATH/$BIN_DIR/python}"
    meridian_config="${meridian_config//REPLACE_KB_PATH/$KNOWLEDGE_BASE_PATH}"

    if [ -f "$oc_config" ]; then
        if grep -q '"meridian"' "$oc_config" 2>/dev/null; then
            log_warn "Meridian already configured in OpenCode. Skipping."
            return
        fi
        log_warn "OpenCode config exists. Add manually:"
        log_warn "$meridian_config"
    else
        echo "$meridian_config" > "$oc_config"
        log_info "Created OpenCode config at $oc_config"
    fi
}

setup_vscode() {
    log_info "Setting up VSCode..."

    local vscode_dir="$HOME/.config/Code/User"
    local vscode_config="$vscode_dir/mcp.json"

    mkdir -p "$vscode_dir"

    local meridian_config=$(cat <<'EOF'
{
  "servers": {
    "meridian": {
      "type": "stdio",
      "command": "REPLACE_BIN_PATH",
      "args": ["-m", "meridian", "mcp"],
      "env": {
        "KNOWLEDGE_BASE_PATH": "REPLACE_KB_PATH",
        "MERIDIAN_ACCESS_LEVEL": "write"
      }
    }
  }
}
EOF
)

    # Replace placeholders
    meridian_config="${meridian_config//REPLACE_BIN_PATH/$BIN_DIR/python}"
    meridian_config="${meridian_config//REPLACE_KB_PATH/$KNOWLEDGE_BASE_PATH}"

    if [ -f "$vscode_config" ]; then
        if grep -q '"meridian"' "$vscode_config" 2>/dev/null; then
            log_warn "Meridian already configured in VSCode. Skipping."
            return
        fi
        log_warn "VSCode config exists. Add manually:"
        log_warn "$meridian_config"
    else
        echo "$meridian_config" > "$vscode_config"
        log_info "Created VSCode config at $vscode_config"
    fi
}

setup_mcp_clients() {
    log_step "Setting up MCP clients..."

    for client in "${CLIENTS_FOUND[@]}"; do
        case "$client" in
            "claude-code")
                setup_claude_code
                ;;
            "kimi-cli")
                setup_kimi_cli
                ;;
            "opencode")
                setup_opencode
                ;;
            "vscode")
                setup_vscode
                ;;
        esac
        echo
    done

    if [ ${#CLIENTS_FOUND[@]} -eq 0 ]; then
        log_warn "No clients configured. Install one and run installer again."
    fi
}

print_summary() {
    echo
    echo "============================================"
    echo -e "${GREEN}Installation complete!${NC}"
    echo "============================================"
    echo
    echo "Installation directory: $INSTALL_DIR"
    echo "Knowledge base:     $KNOWLEDGE_BASE_PATH"
    echo "MCP Clients:    ${CLIENTS_FOUND[*]:-none}"
    echo
    echo "To start Meridian:"
    echo "  $BIN_DIR/python -m meridian mcp"
    echo
    echo "Manual configuration for other clients:"
    echo "  KNOWLEDGE_BASE_PATH=$KNOWLEDGE_BASE_PATH"
    echo "  MERIDIAN_ACCESS_LEVEL=write"
    echo "  Command: $BIN_DIR/python -m meridian mcp"
    echo
}

print_usage() {
    cat <<EOF
Meridian Installer v1.2.0

Usage:
  bash install.sh                      # Interactive installation
  curl -fsSL URL | bash             # Remote installation

Options:
  INSTALL_DIR=/path     Custom installation directory (default: ~/.meridian)
  KNOWLEDGE_BASE_PATH=/path  Custom knowledge base path
  SKIP_MCP=1         Skip MCP client configuration
  DRY_RUN=1          Show what would be done without executing

Examples:
  # Default installation
  bash install.sh

  # Custom directories
  INSTALL_DIR=/opt/meridian KNOWLEDGE_BASE_PATH=/data/kb bash install.sh

  # Remote installation
  curl -fsSL https://raw.githubusercontent.com/axiom-juma/meridian/main/scripts/install.sh | bash

  # Dry run (show what would happen)
  DRY_RUN=1 bash install.sh

EOF
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
    echo -e "  ${GREEN}Meridian Installer v1.2.0${NC}"
    echo "════════════════════════════════════════════════"
    echo

    log_info "Options:"
    echo "  Install directory:  $INSTALL_DIR"
    echo "  Knowledge base:    ${KNOWLEDGE_BASE_PATH:-auto}"
    echo "  Skip MCP setup:     ${SKIP_MCP:-no}"
    echo "  Dry run:          ${DRY_RUN:-no}"
    echo

    check_prerequisites
    check_network
    detect_os

    if [ "$DRY_RUN" = "1" ]; then
        log_warn "[DRY RUN] Would proceed with installation"
        log_info "Would detect MCP clients: $(detect_mcp_clients 2>&1 | grep -c 'Found' 2>/dev/null || echo '0')"
        log_info "Would install to: $INSTALL_DIR"
        log_info "Would create KB at: ${KNOWLEDGE_BASE_PATH:-$(get_default_kb_path)}"
        log_info "Dry run complete. Run without DRY_RUN=1 to install."
        exit 0
    fi

    detect_mcp_clients
    create_install_dir
    setup_venv
    install_meridian
    create_knowledge_base

    if [ "$SKIP_MCP" != "1" ]; then
        setup_mcp_clients
    else
        log_warn "Skipping MCP client configuration (SKIP_MCP=1)"
    fi

    print_summary
}

main "$@"