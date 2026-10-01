"""Access control, session tokens, and audit logging."""

import getpass
import json
import os
import secrets
import sqlite3
from typing import Any

# --- Access levels ---

TOOL_ACCESS_LEVELS: dict[str, str] = {
    # read
    "query_rules": "read",
    "query_lessons": "read",
    "get_rule_context": "read",
    "get_rule_timeline": "read",
    "get_project_scope_resolution": "read",
    "get_server_info": "read",
    "get_rule_audit_log": "read",
    "list_pending_proposals": "read",
    "get_rule_template": "read",
    "get_lesson_template": "read",
    "get_transcription_template": "read",
    # analyze
    "audit_pr": "analyze",
    "analyze_pr_feedback": "analyze",
    "check_feature_against_rules": "analyze",
    "extract_rules_from_transcript": "analyze",
    "extract_lessons_from_transcript": "analyze",
    "create_pending_proposal": "analyze",
    "deprecate_rule": "analyze",
    # write
    "index_rules_from_markdown": "write",
    "index_lessons_from_markdown": "write",
    "convert_to_atomic_format": "write",
    "approve_proposal": "write",
    "edit_proposal": "write",
    "reject_proposal": "write",
    "promote_rule": "write",
    "create_project": "write",
    "generate_embeddings": "write",
    "generate_project_skills": "write",
}

LEVEL_HIERARCHY = {"read": 0, "analyze": 1, "write": 2}


class AccessDeniedError(Exception):
    """Raised when a tool is invoked with insufficient access level."""

    def __init__(self, tool_name: str, required: str, current: str):
        self.tool_name = tool_name
        self.required = required
        self.current = current
        super().__init__(
            f"Tool '{tool_name}' requires access level '{required}'. "
            f"Current level: '{current}'. "
            f"Set MERIDIAN_ACCESS_LEVEL={required} to enable."
        )


def get_access_level() -> str:
    """
    Lee MERIDIAN_ACCESS_LEVEL del entorno.
    Valores válidos: "read", "analyze", "write".
    Default: "analyze".
    Si el valor no es válido, lanza ValueError.
    """
    level = os.environ.get("MERIDIAN_ACCESS_LEVEL", "analyze").lower()
    if level not in LEVEL_HIERARCHY:
        raise ValueError(
            f"Invalid MERIDIAN_ACCESS_LEVEL='{level}'. Valid values: read, analyze, write"
        )
    return level


def check_access(tool_name: str) -> None:
    """
    Verifica que el nivel de acceso actual permite invocar el tool.
    Lanza AccessDeniedError si el nivel es insuficiente.
    """
    required = TOOL_ACCESS_LEVELS.get(tool_name)
    if required is None:
        return  # tool no registrado en el mapa → permitir (forward-compatible)
    current = get_access_level()
    if LEVEL_HIERARCHY[current] < LEVEL_HIERARCHY[required]:
        raise AccessDeniedError(tool_name, required, current)


# --- Actor identity (openspec/changes/add-actor-identity-tracking) ---

_VALID_MODES = {"local", "shared"}

# Returned by resolve_actor() in local mode when getpass.getuser() itself
# can't resolve an OS user (e.g. some containers/CI have no password-database
# entry for the running uid) — attribution must never break a write path
# that worked before this feature existed.
_UNKNOWN_LOCAL_ACTOR = "unknown-local-user"


def get_mode() -> str:
    """
    Lee MERIDIAN_MODE del entorno.
    Valores válidos: "local", "shared".
    Default: "local".
    Si el valor no es válido, lanza ValueError.
    """
    mode = os.environ.get("MERIDIAN_MODE", "local").lower()
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Invalid MERIDIAN_MODE='{mode}'. Valid values: local, shared"
        )
    return mode


def resolve_actor() -> str:
    """
    Resuelve el actor que origina la llamada actual, para atribución en
    access_log/pending_proposals/rule_history/lesson_history.

    En modo "local" (default), es el usuario del SO (getpass.getuser()) —
    sin credenciales, sin configuración adicional. No afecta check_access:
    esta función es solo para atribución, nunca para autorización.
    """
    mode = get_mode()
    if mode == "shared":
        raise NotImplementedError(
            "MERIDIAN_MODE=shared is not yet implemented — see "
            "openspec/changes/add-actor-identity-tracking/design.md"
        )
    try:
        return getpass.getuser()
    except OSError:
        return _UNKNOWN_LOCAL_ACTOR


# --- Session token (HTTP/SSE only) ---


def generate_session_token() -> str:
    """Genera un token aleatorio de 32 bytes URL-safe. Cambia en cada reinicio."""
    return secrets.token_urlsafe(32)


def validate_session_token(provided: str | None, expected: str) -> bool:
    """Compara tokens en tiempo constante para prevenir timing attacks."""
    if provided is None:
        return False
    return secrets.compare_digest(provided, expected)


# --- Audit log ---

# Parámetros que NUNCA se incluyen en el log (contenido sensible)
SENSITIVE_PARAMS = {"pr_diff", "feedback_text", "text", "proposed_text", "new_text"}


def extract_safe_params(kwargs: dict[str, Any]) -> str:
    """
    Extrae parámetros seguros para logging.
    Excluye campos listados en SENSITIVE_PARAMS.
    Retorna JSON string.
    """
    safe = {k: v for k, v in kwargs.items() if k not in SENSITIVE_PARAMS}
    for k, v in safe.items():
        if isinstance(v, str) and len(v) > 200:
            safe[k] = v[:200] + "...[truncated]"
    # Hash (nunca el valor en claro) para poder correlacionar accesos repetidos
    # a un mismo dato sensible sin exponer su contenido en el audit log.
    for k, v in kwargs.items():
        if k in SENSITIVE_PARAMS and isinstance(v, str):
            import hashlib

            safe[f"{k}_sha256"] = hashlib.sha256(v.encode()).hexdigest()[:12]
    return json.dumps(safe, ensure_ascii=False, default=str)


def log_tool_access(
    conn: sqlite3.Connection,
    log_id: str,
    tool_name: str,
    access_level: str,
    project_id: str | None,
    parameters: str,
    result: str,
    transport: str,
    actor_id: str | None = None,
) -> None:
    """Inserta un registro en access_log."""
    conn.execute(
        "INSERT INTO access_log (id, tool_name, access_level, project_id, "
        "parameters, result, transport, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            log_id,
            tool_name,
            access_level,
            project_id,
            parameters,
            result,
            transport,
            actor_id,
        ),
    )
    conn.commit()
