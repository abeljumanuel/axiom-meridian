# Axiom Meridian — Plan de Implementación Determinista

**Referencia:** PRD v1.3 · ADR-001 · ADR-002  
**Date:** 2026-04-19  
**Instrucción:** Ejecutar las fases en orden. No iniciar una fase sin que el gate de la anterior esté aprobado. Cada paso produce exactamente un entregable verificable.

---

## Prerrequisitos

Antes de iniciar cualquier fase, ejecutar exactamente estos comandos:

```bash
# 1. Verificar Python
python3 --version
# Resultado esperado: Python 3.11.x o superior. Si no → instalar Python 3.11+

# 2. Instalar uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# En Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 3. Crear directorio del proyecto
mkdir meridian && cd meridian
git init

# 4. Crear directorio de la knowledge-base (fuera del repo)
mkdir -p ~/meridian-kb/knowledge-base/global
mkdir -p ~/meridian-kb/knowledge-base/projects
mkdir -p ~/meridian-kb/lessons/global
mkdir -p ~/meridian-kb/lessons/projects

# 5. Exportar variables de entorno
export KNOWLEDGE_BASE_PATH=~/meridian-kb
export MERIDIAN_PROJECT_PATH=$(pwd)  # solo necesario si se usa generate_project_skills
export MERIDIAN_ACCESS_LEVEL=write   # "read" | "analyze" | "write". Default: "analyze"
```

**Gate de prerrequisitos:** `python3 --version` retorna 3.11+. `uv --version` retorna versión válida. Ambos directorios existen.

---

## FASE 1 — Estructura del paquete Python

**Objetivo:** Un paquete instalable que responde a `python -m meridian --version`.

### Paso 1.1 — Crear `pyproject.toml`

**Archivo:** `pyproject.toml` en la raíz del repo.

**Contenido obligatorio:**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "axiom-meridian"
version = "0.1.0"
description = "Knowledge audit MCP server — Code drifts. Meridian doesn't."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Axiom JUMA" }]

dependencies = [
    "fastmcp>=0.4.0",
    "httpx>=0.27.0",
    "sentence-transformers>=3.0.0",
    "chromadb>=0.5.0",
    "torch>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.5.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/meridian"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

**Restricción:** No agregar ninguna dependencia que no esté en esta lista. No usar Poetry — usar `uv` + `hatchling`.

### Paso 1.2 — Crear estructura de paquete

Crear exactamente estos archivos con este contenido:

**Archivo:** `src/meridian/__init__.py`
```python
"""Axiom Meridian — Knowledge audit MCP server."""

__version__ = "0.1.0"
```

**Archivo:** `src/meridian/__main__.py`
```python
"""Entry point for `python -m meridian`."""

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m meridian [mcp|serve|version]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "version":
        from meridian import __version__
        print(f"Axiom Meridian v{__version__}")

    elif command == "mcp":
        from meridian.server import run_stdio
        run_stdio()

    elif command == "serve":
        from meridian.server import run_http
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
        run_http(port)

    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m meridian [mcp|serve|version]")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Archivo:** `src/meridian/server.py` (stub inicial)
```python
"""FastMCP server — stub until tools are registered."""


def run_stdio() -> None:
    print("MCP stdio server — not yet implemented")


def run_http(port: int = 8080) -> None:
    print(f"HTTP/SSE server on port {port} — not yet implemented")
```

**Archivo:** `src/meridian/config.py`
```python
"""Configuration — environment variables and platform detection."""

import os
import platform
from pathlib import Path


def get_knowledge_base_path() -> Path:
    raw = os.environ.get("KNOWLEDGE_BASE_PATH")
    if not raw:
        raise RuntimeError(
            "KNOWLEDGE_BASE_PATH environment variable is not set. "
            "Set it to the directory containing your knowledge-base/ and lessons/ folders."
        )
    path = Path(raw).resolve()
    if not path.is_dir():
        raise RuntimeError(
            f"KNOWLEDGE_BASE_PATH={raw} does not exist or is not a directory."
        )
    return path


def get_project_path() -> Path | None:
    raw = os.environ.get("MERIDIAN_PROJECT_PATH")
    if not raw:
        return None
    return Path(raw).resolve()


def get_db_path() -> Path:
    return get_knowledge_base_path() / "meridian.db"


def get_chroma_path() -> Path:
    return get_knowledge_base_path() / "chroma"


def get_access_level() -> str:
    """
    Lee MERIDIAN_ACCESS_LEVEL. Valores: "read", "analyze", "write".
    Default: "analyze". Validación completa en security.py.
    """
    return os.environ.get("MERIDIAN_ACCESS_LEVEL", "analyze").lower()


def get_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine == "arm64":
        return "macos-apple-silicon"
    elif system == "darwin":
        return "macos-intel"
    elif system == "linux":
        return "linux"
    elif system == "windows":
        return "windows"
    return "unknown"
```

### Paso 1.3 — Instalar y verificar

```bash
uv pip install -e ".[dev]"
python -m meridian version
```

**Gate de Fase 1:** El comando `python -m meridian version` imprime `Axiom Meridian v0.1.0`. El comando `python -c "from meridian.config import get_platform; print(get_platform())"` imprime el nombre de la plataforma actual.

---

## FASE 2 — Base de datos SQLite

**Objetivo:** DB inicializada con schema completo, scopes, y atributos. Funciones de conexión probadas.

### Paso 2.1 — Crear `schema.sql`

**Archivo:** `src/meridian/db/schema.sql`

**Contenido:** Copiar textualmente el schema SQL completo de la sección 4 del PRD v1.2, incluyendo:
- Las 13 tablas: `scopes`, `scope_attributes`, `rules`, `rule_attributes`, `rule_history`, `lesson_history`, `lessons`, `rule_lesson_links`, `project_scope_resolution`, `pr_audits`, `planning_checks`, `pending_proposals`, `access_log`
- Los 8 índices
- Los 12 INSERTs de scopes de la sección 4.2
- Los 11 INSERTs de scope_attributes de la sección 4.2

**Restricción:** El archivo `schema.sql` debe ser ejecutable en una sola llamada a `cursor.executescript()`. Cada statement termina en `;`. No usar `CREATE TABLE IF NOT EXISTS` — el schema se aplica solo una vez en DB vacía.

### Paso 2.2 — Crear `connection.py`

**Archivo:** `src/meridian/db/connection.py`

**Responsabilidades exactas:**

1. Función `get_connection(db_path: Path) -> sqlite3.Connection` — abre o crea la DB. Activa `PRAGMA journal_mode=WAL` y `PRAGMA foreign_keys=ON`. Retorna la conexión.

2. Función `initialize_db(db_path: Path) -> None` — verifica si la tabla `scopes` existe. Si no existe, lee `schema.sql` (localizado via `Path(__file__).parent / "schema.sql"`) y ejecuta `cursor.executescript(sql)`. Si ya existe, no hace nada.

3. No usar ORM. No usar connection pool. Usar `sqlite3` de la stdlib.

### Paso 2.3 — Crear `id_generator.py`

**Archivo:** `src/meridian/utils/id_generator.py`

**Funciones exactas:**

```python
def next_rule_code(conn: sqlite3.Connection, scope_id: str) -> str:
    """
    Genera el siguiente código de regla para un scope.
    Extrae el segmento tech del scope_id:
      "global-java" → "JAVA"
      "global-quarkus" → "QUARKUS"
      "project-psp-integrator" → "PSP"
    Consulta MAX(code) en rules WHERE code LIKE 'RN-{TECH}-%'
    Incrementa el número. Si no hay registros, inicia en 001.
    Retorna: "RN-JAVA-011"
    """

def next_lesson_code(conn: sqlite3.Connection, scope_id: str) -> str:
    """
    Similar a next_rule_code pero para lecciones.
    "project-psp-integrator" → "PSP"
    Retorna: "LL-PSP-003"
    """

def next_sequential_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    """
    Para tablas con ID secuencial genérico.
    table: "pending_proposals" | "pr_audits" | "planning_checks" | "rule_history" | "lesson_history"
    prefix: "prop" | "audit" | "check" | "rh" | "lh"
    Consulta MAX(id) en la tabla WHERE id LIKE '{prefix}-%'
    Retorna: "prop-0041"
    """
```

**Regla para el segmento tech/project:** Tomar la última parte del `scope_id` después del último `-`. Si el scope es `project-psp-integrator`, tomar `psp`. Si es `global-java`, tomar `java`. Si es `global-go-fiber`, tomar `fiber`. Convertir a mayúsculas.

**Excepción:** Si `scope_id` es `global` (sin guión), usar `GLOBAL` como segmento.

### Paso 2.4 — Tests unitarios de Fase 2

**Archivo:** `tests/unit/test_connection.py`

Tests exactos:
1. `test_initialize_creates_all_tables` — ejecuta `initialize_db` en una DB temporal. Verifica que las 13 tablas existen via `SELECT name FROM sqlite_master WHERE type='table'`.
2. `test_initialize_inserts_scopes` — ejecuta `initialize_db`. Verifica que `SELECT COUNT(*) FROM scopes` retorna 12.
3. `test_initialize_inserts_scope_attributes` — verifica que `SELECT COUNT(*) FROM scope_attributes` retorna 19.
4. `test_initialize_is_idempotent` — ejecuta `initialize_db` dos veces. No lanza error. Conteos iguales.

**Archivo:** `tests/unit/test_id_generator.py`

Tests exactos:
1. `test_next_rule_code_first_rule` — DB vacía, `scope_id="global-java"` → retorna `"RN-JAVA-001"`.
2. `test_next_rule_code_increments` — insertar una regla con code `RN-JAVA-005`. Llamar `next_rule_code` → retorna `"RN-JAVA-006"`.
3. `test_next_lesson_code` — `scope_id="project-psp-integrator"` → retorna `"LL-PSP-001"`.
4. `test_next_sequential_id` — tabla `pending_proposals`, prefix `prop` → retorna `"prop-0001"`.
5. `test_scope_id_global` — `scope_id="global"` → segmento es `"GLOBAL"` → retorna `"RN-GLOBAL-001"`.

### Paso 2.5 — Ejecutar y verificar

```bash
python -m pytest tests/unit/test_connection.py tests/unit/test_id_generator.py -v
```

**Gate de Fase 2:** Todos los tests pasan. La DB se crea en un directorio temporal con las 13 tablas, 12 scopes y 19 atributos.

---

## FASE 3 — Utilidades core

**Objetivo:** `privacy.py`, `serializers.py`, `security.py` probados y aislados.

### Paso 3.1 — Crear `privacy.py`

**Archivo:** `src/meridian/utils/privacy.py`

**Función exacta:**

```python
import re

PRIVATE_PATTERN = re.compile(r"<private>.*?</private>", re.DOTALL)


def strip_private_tags(text: str) -> str:
    """
    Reemplaza todo contenido entre <private>...</private> con [REDACTED].
    Soporta tags multilínea (re.DOTALL).
    Si text es None, retorna None.
    Si no hay tags, retorna text sin cambios.
    """
    if text is None:
        return None
    return PRIVATE_PATTERN.sub("[REDACTED]", text)
```

### Paso 3.2 — Crear `serializers.py`

**Archivo:** `src/meridian/utils/serializers.py`

**Funciones exactas:**

```python
import json
from typing import Any


def json_encode(records: list[dict[str, Any]]) -> str:
    """Serializa una lista de diccionarios a JSON compact."""
    return json.dumps(records, ensure_ascii=False, separators=(",", ":"))


def toon_encode(records: list[dict[str, Any]], fields: list[str]) -> str:
    """
    Serializa una lista de diccionarios uniformes a formato TOON (ADR-001).

    Formato de salida:
    items[N]{field1,field2,...}:
      value1,value2,...
      value1,value2,...

    Reglas de encoding por valor:
    - str con comas → envolver en comillas dobles: "value,with,commas"
    - str con comillas dobles → escapar con doble comilla: "value ""quoted"""
    - None → (vacío, sin caracteres)
    - bool → true | false (minúsculas)
    - int/float → representación string directa
    - list → JSON inline: ["tag1","tag2"]
    - Cualquier otro tipo → str(value)
    """


def serialize(records: list[dict[str, Any]], format: str = "json",
              fields: list[str] | None = None) -> str:
    """
    Router de serialización. Único punto de entrada para los tools.
    format: "json" | "toon"
    fields: requerido si format="toon", ignorado si format="json"
    Lanza ValueError si format no es "json" ni "toon".
    """
    if format == "json":
        return json_encode(records)
    elif format == "toon":
        if fields is None:
            raise ValueError("fields parameter is required for TOON format")
        return toon_encode(records, fields)
    else:
        raise ValueError(f"Unknown format: {format}. Valid: 'json', 'toon'")
```

### Paso 3.3 — Crear `security.py`

**Archivo:** `src/meridian/utils/security.py`

**Contenido obligatorio:**

```python
"""Access control, session tokens, and audit logging."""

import os
import secrets
import json
import sqlite3
from functools import wraps
from typing import Any

# --- Access levels ---

TOOL_ACCESS_LEVELS: dict[str, str] = {
    # read
    "query_rules": "read",
    "query_lessons": "read",
    "get_rule_context": "read",
    "get_rule_timeline": "read",
    "get_project_scope_resolution": "read",
    "get_rule_audit_log": "read",
    "list_pending_proposals": "read",
    # analyze
    "audit_pr": "analyze",
    "analyze_pr_feedback": "analyze",
    "check_feature_against_rules": "analyze",
    "extract_rules_from_transcript": "analyze",
    "extract_lessons_from_transcript": "analyze",
    "create_pending_proposal": "analyze",
    # write
    "index_rules_from_markdown": "write",
    "index_lessons_from_markdown": "write",
    "convert_to_atomic_format": "write",
    "approve_proposal": "write",
    "edit_proposal": "write",
    "reject_proposal": "write",
    "promote_rule": "write",
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
            f"Invalid MERIDIAN_ACCESS_LEVEL='{level}'. "
            f"Valid values: read, analyze, write"
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
    # Truncar valores string largos a 200 caracteres
    for k, v in safe.items():
        if isinstance(v, str) and len(v) > 200:
            safe[k] = v[:200] + "...[truncated]"
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
) -> None:
    """Inserta un registro en access_log."""
    conn.execute(
        "INSERT INTO access_log (id, tool_name, access_level, project_id, "
        "parameters, result, transport) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (log_id, tool_name, access_level, project_id, parameters, result, transport),
    )
    conn.commit()
```

**Restricción:** El decorator `@log_access` que compone `check_access` + `log_tool_access` se implementa en `server.py` (Fase 11) porque necesita acceso al contexto de transporte (stdio vs http). En esta fase solo se implementan las funciones primitivas.

### Paso 3.4 — Tests unitarios de Fase 3

**Archivo:** `tests/unit/test_privacy.py`

Tests exactos:
1. `test_strip_single_tag` — `"text <private>secret</private> more"` → `"text [REDACTED] more"`
2. `test_strip_multiline` — tag que cruza líneas → `[REDACTED]`
3. `test_strip_multiple_tags` — dos tags en el mismo texto → ambos reemplazados
4. `test_no_tags` — texto sin tags → retorna igual
5. `test_none_input` — `None` → `None`
6. `test_nested_content` — `<private>key=sk-xxx\ntoken=abc</private>` → `[REDACTED]`

**Archivo:** `tests/unit/test_serializers.py`

Tests exactos:
1. `test_json_encode_list` — 2 registros → JSON compact válido, parseable con `json.loads()`
2. `test_toon_encode_simple` — 2 registros, 3 campos → header `items[2]{f1,f2,f3}:` + 2 líneas de datos
3. `test_toon_encode_commas` — valor con coma → envuelto en comillas dobles
4. `test_toon_encode_none` — campo None → celda vacía (sin caracteres entre comas)
5. `test_toon_encode_bool` — True/False → `true`/`false` (minúsculas)
6. `test_serialize_router_json` — `format="json"` → llama `json_encode`
7. `test_serialize_router_toon` — `format="toon"` con fields → llama `toon_encode`
8. `test_serialize_router_invalid` — `format="xml"` → `ValueError`
9. `test_serialize_toon_without_fields` — `format="toon"` sin fields → `ValueError`

**Archivo:** `tests/unit/test_security.py`

Tests exactos:
1. `test_get_access_level_default` — sin variable de entorno → retorna `"analyze"`.
2. `test_get_access_level_read` — `MERIDIAN_ACCESS_LEVEL=read` → retorna `"read"`.
3. `test_get_access_level_invalid` — `MERIDIAN_ACCESS_LEVEL=admin` → `ValueError`.
4. `test_check_access_read_allows_query` — nivel `read`, tool `query_rules` → no lanza error.
5. `test_check_access_read_denies_approve` — nivel `read`, tool `approve_proposal` → `AccessDeniedError`.
6. `test_check_access_write_allows_all` — nivel `write`, tool `approve_proposal` → no lanza error.
7. `test_check_access_analyze_allows_audit` — nivel `analyze`, tool `audit_pr` → no lanza error.
8. `test_check_access_analyze_denies_write` — nivel `analyze`, tool `generate_embeddings` → `AccessDeniedError`.
9. `test_check_access_hierarchy_inclusion` — nivel `write` permite tools de nivel `read` y `analyze`.
10. `test_extract_safe_params_strips_sensitive` — kwargs con `pr_diff` y `project_id` → solo `project_id` en resultado.
11. `test_extract_safe_params_truncates_long` — string de 500 chars → truncado a 200 + `...[truncated]`.
12. `test_generate_session_token_unique` — dos llamadas → tokens diferentes.
13. `test_validate_session_token_correct` — token correcto → `True`.
14. `test_validate_session_token_wrong` — token incorrecto → `False`.
15. `test_validate_session_token_none` — `None` → `False`.
16. `test_access_denied_error_message` — verificar que el mensaje incluye tool, required level, y current level.

```bash
python -m pytest tests/unit/test_privacy.py tests/unit/test_serializers.py tests/unit/test_security.py -v
```

**Gate de Fase 3:** Todos los tests pasan. Los 3 módulos (`privacy.py`, `serializers.py`, `security.py`) son importables y sus funciones públicas están probadas.

---

## FASE 4 — Parsers Markdown

**Objetivo:** Los dos parsers (atómico y legacy) extraen bloques con `file_offset` y `byte_length` correctos.

### Paso 4.1 — Crear archivo seed de ejemplo

**Archivo:** `knowledge-base/global/java.md`

**Contenido exacto** (extraído del `Global_Rules.md` real):

```markdown
## RN-JAVA-001
**Scope:** global-java
**Categoría:** architecture
**Severidad:** critical
**Aplica a:** **/*.java
**Tags:** imperative, reactive, quarkus
**Fuente:** tech-lead-directive-2026-01
**Regla:** Imperative model only — Java 21 (Temurin) + Quarkus. No Mutiny, no reactive extensions. All code must be synchronous/imperative.

## RN-JAVA-002
**Scope:** global-java
**Categoría:** logging
**Severidad:** critical
**Aplica a:** **/*.java
**Tags:** slf4j, fluent-api, datadog, structured-logging
**Fuente:** tech-lead-directive-2026-01
**Regla:** Always use @Slf4j (Lombok) with the SLF4J Fluent API for structured logging compatible with Datadog. Never use org.jboss.logging.Logger or Logger.getLogger(). Use key-value pairs over string interpolation.

## RN-JAVA-003
**Scope:** global-java
**Categoría:** dependency-injection
**Severidad:** high
**Aplica a:** **/*.java
**Tags:** cdi, constructor-injection, lombok
**Fuente:** tech-lead-directive-2026-01
**Regla:** Constructor injection over field injection. Prefer @RequiredArgsConstructor or explicit constructors over @Inject on fields. Omit @Inject on single-constructor beans (CDI 4.0 auto-discovers). Exception: required when @ConfigProperty params are present or multiple constructors exist.
```

### Paso 4.2 — Crear `atomic_parser.py`

**Archivo:** `src/meridian/parsers/atomic_parser.py`

**Entrada:** `filepath: str` (ruta relativa a `KNOWLEDGE_BASE_PATH` o absoluta)

**Salida:** `list[ParsedBlock]` donde:

```python
@dataclass
class ParsedBlock:
    code: str            # "RN-JAVA-001"
    scope: str | None    # valor del campo **Scope:** o None si no existe
    category: str | None
    severity: str | None
    applies_to: str | None
    tags: list[str]
    source: str | None
    text: str            # valor del campo **Regla:** o **Qué pasó:** (todo el contenido restante)
    file_path: str       # ruta del archivo fuente
    file_offset: int     # byte offset del inicio del bloque (posición del `##`)
    byte_length: int     # largo en bytes del bloque completo
```

**Algoritmo de parsing:**

1. Leer el archivo completo en bytes (`rb`). Guardar como `raw_bytes`.
2. Decodificar a string UTF-8.
3. Buscar todos los bloques que empiezan con `## RN-` o `## LL-` usando regex: `^## (RN|LL)-[A-Z]+-\d+`
4. Para cada match:
   a. `file_offset` = posición en bytes del inicio del match en `raw_bytes`
   b. `byte_length` = distancia en bytes desde el inicio de este bloque hasta el inicio del siguiente bloque (o EOF)
   c. Extraer el texto del bloque (entre este `##` y el siguiente `##` o EOF)
   d. Parsear campos `**Campo:** valor` via regex: `\*\*([^*]+):\*\*\s*(.+)`
   e. El campo `**Regla:**` o `**Qué pasó:**` puede ser multilínea — capturar todo hasta el final del bloque
   f. `tags` se parsea como lista separada por comas: `"a, b, c"` → `["a", "b", "c"]`

**Verificación de offsets:** `raw_bytes[offset:offset+length].decode('utf-8')` debe reproducir exactamente el texto del bloque original. Si no coincide, el parser tiene un bug.

**Campos no encontrados:** Si un campo obligatorio no existe en el bloque, setear como `None` y reportar en warnings. No lanzar error — permitir indexación parcial.

### Paso 4.3 — Crear `legacy_parser.py`

**Archivo:** `src/meridian/parsers/legacy_parser.py`

**Entrada:** `filepath: str`, `doc_type: str` (`"rules"` | `"lessons"`)

**Salida:** `list[LegacyBlock]` donde:

```python
@dataclass
class LegacyBlock:
    title: str           # "Issue 1.2: Lombok Annotation Qualifier Omission"
    section: str         # "Phase 1 — Contracts Layer"
    fields: dict         # campos extraídos: {"Problem": "...", "Resolution": "...", ...}
    raw_text: str        # texto original completo del bloque
    file_path: str
    file_offset: int
    byte_length: int
```

**Algoritmo de parsing:**

1. Leer archivo completo en bytes. Decodificar UTF-8.
2. Identificar secciones `## ` (nivel 2) como agrupadores de fase/sección.
3. Identificar bloques `### ` (nivel 3) como unidades individuales.
4. Para cada bloque `###`:
   a. Extraer `title` del heading.
   b. Extraer campos `- **Campo**: valor` o `**Campo:** valor`.
   c. Si el heading contiene "Verification:", "Skill Suggestions", o empieza con `/` → **descartar silenciosamente**. No incluir en el resultado.
   d. Calcular `file_offset` y `byte_length` exactos en bytes.
   e. Guardar `raw_text` como el texto original completo.

5. Para `doc_type="rules"`: los campos esperados en `Global_Rules.md` son bloques con bullets `- **texto** — explicación`. Cada bullet es un candidato a regla individual.

6. Para `doc_type="lessons"`: los campos esperados son `Problem`, `Resolution`, `Learning` (o variantes como `Step`).

**Restricción:** El parser legacy nunca genera IDs. Solo extrae contenido. Los IDs se generan al crear `pending_proposals` vía `id_generator.py`.

### Paso 4.4 — Tests unitarios de Fase 4

**Archivo:** `tests/unit/test_atomic_parser.py`

Tests exactos:
1. `test_parse_seed_file` — parsear `knowledge-base/global/java.md` → 3 bloques.
2. `test_block_codes` — los 3 bloques tienen codes `RN-JAVA-001`, `RN-JAVA-002`, `RN-JAVA-003`.
3. `test_block_scope` — los 3 bloques tienen scope `global-java`.
4. `test_block_severity` — bloques 1 y 2: `critical`. Bloque 3: `high`.
5. `test_block_tags` — bloque 2 tiene `["slf4j", "fluent-api", "datadog", "structured-logging"]`.
6. `test_positional_read` — para cada bloque, leer `raw_bytes[offset:offset+length]` y verificar que contiene el `code` del bloque.
7. `test_empty_file` — archivo vacío → lista vacía, sin error.
8. `test_missing_scope_field` — bloque sin `**Scope:**` → `scope` es `None`, aparece en warnings.

**Archivo:** `tests/unit/test_legacy_parser.py`

Tests exactos (usar un fixture de texto inline, no el archivo real):
1. `test_parse_lessons_format` — texto con `### Issue 1.1: Title` + `- **Problem**: ...` + `- **Resolution**: ...` → 1 bloque con fields correctos.
2. `test_skip_verification_sections` — texto con `### Verification: Phase 0` → descartado, no aparece en resultados.
3. `test_skip_skill_suggestions` — texto con `### /pr-implement` → descartado.
4. `test_multiple_blocks` — 3 bloques `###` → 3 `LegacyBlock` con offsets correctos.
5. `test_positional_read_legacy` — verificar que `raw_bytes[offset:offset+length]` reproduce el bloque original.

```bash
python -m pytest tests/unit/test_atomic_parser.py tests/unit/test_legacy_parser.py -v
```

**Gate de Fase 4:** Todos los tests pasan. La lectura posicional (`raw_bytes[offset:offset+length]`) reproduce exactamente el texto de cada bloque en ambos parsers.

---

## FASE 5 — Scope Resolver

**Objetivo:** Resolución de jerarquía de scopes con filtrado por atributos dinámicos (ADR-002).

### Paso 5.1 — Crear `scope_resolver.py`

**Archivo:** `src/meridian/utils/scope_resolver.py`

**Funciones exactas:**

```python
def resolve_scope_hierarchy(conn: sqlite3.Connection, project_id: str) -> list[str]:
    """
    Resuelve la cadena de scopes desde el proyecto hasta global.
    Retorna lista ordenada por precedencia: [project, parent, grandparent, ..., global]

    Algoritmo:
    1. SELECT parent_id FROM scopes WHERE id = project_id
    2. Iterar siguiendo parent_id hasta parent_id IS NULL
    3. Retorna la lista completa incluyendo el project_id inicial

    Si project_id no existe en scopes → lanzar ValueError con scopes válidos listados.
    """


def load_scope_attributes(conn: sqlite3.Connection, scope_id: str) -> dict[str, str]:
    """
    SELECT key, value FROM scope_attributes WHERE scope_id = ?
    Retorna dict: {"framework": "quarkus", "component_role": "gateway"}
    Si no hay atributos → retorna dict vacío.
    """


def filter_by_attributes(
    conn: sqlite3.Connection,
    rule_ids: list[str],
    project_attributes: dict[str, str]
) -> list[str]:
    """
    Filtra reglas por compatibilidad de atributos (ADR-002).

    Para cada rule_id:
    1. SELECT key, value FROM rule_attributes WHERE rule_id = ?
    2. Si no hay rule_attributes → INCLUIR (aplica a todos)
    3. Si hay rule_attributes → INCLUIR solo si TODOS los atributos
       coinciden con project_attributes (AND logic)
    4. Si un key de rule_attributes no existe en project_attributes → INCLUIR
       (inclusión conservadora para prevenir pérdida de conocimiento)

    Retorna lista de rule_ids que pasan el filtro.
    """
```

### Paso 5.2 — Tests unitarios

**Archivo:** `tests/unit/test_scope_resolver.py`

Tests exactos (usar DB inicializada con datos seed):
1. `test_resolve_psp_integrator` — `"project-psp-integrator"` → `["project-psp-integrator", "global-quarkus", "global-java", "global"]`
2. `test_resolve_pac_module` — `"project-pac-module"` → `["project-pac-module", "global-nestjs", "global"]`
3. `test_resolve_nonexistent` — `"project-nonexistent"` → `ValueError`
4. `test_load_attributes_psp` — `"project-psp-integrator"` → `{"framework": "quarkus", "component_role": "gateway", "runtime_version": "java-21"}`
5. `test_load_attributes_empty` — `"global"` → `{}`
6. `test_filter_no_attributes` — regla sin `rule_attributes` → incluida siempre
7. `test_filter_matching_attributes` — regla con `framework=quarkus`, proyecto con `framework=quarkus` → incluida
8. `test_filter_non_matching` — regla con `framework=nestjs`, proyecto con `framework=quarkus` → excluida
9. `test_filter_unknown_key` — regla con `team=payments`, proyecto sin key `team` → incluida (conservadora)
10. `test_filter_and_logic` — regla con `framework=quarkus` + `component_role=gateway`, proyecto con ambos → incluida. Proyecto solo con `framework=quarkus` (sin `component_role`) → incluida (conservadora en keys ausentes). Proyecto con `component_role=worker` → excluida.

```bash
python -m pytest tests/unit/test_scope_resolver.py -v
```

**Gate de Fase 5:** Todos los tests pasan. La resolución de jerarquía sigue la cadena `parent_id` exacta. El filtrado por atributos cumple las 3 reglas: sin atributos → incluir, match → incluir, key desconocido → incluir, mismatch → excluir.

---

## FASE 6 — Tools de Knowledge Management (indexación y propuestas)

**Objetivo:** `index_rules_from_markdown()` en ambos modos funciona end-to-end. `approve_proposal()` escribe al `.md` y actualiza SQLite.

### Paso 6.1 — Implementar `index_rules_from_markdown`

**Archivo:** `src/meridian/tools/knowledge_management.py`

**Comportamiento modo `atomic`:**
1. Llamar `atomic_parser.parse(filepath)`.
2. Para cada bloque: determinar `scope_id` (del campo `**Scope:**` si existe, sino de `default_scope_id`).
3. Verificar que `scope_id` existe en `scopes`. Si no → registrar error, continuar con el siguiente bloque.
4. Verificar si ya existe una regla con el mismo `code` en `rules`.
   - Si existe y el texto es diferente → UPDATE + registrar en `rule_history` con `change_type=UPDATED`.
   - Si existe y el texto es igual → skip.
   - Si no existe → INSERT + registrar en `rule_history` con `change_type=CREATED`.
5. Dejar `embedding_id = NULL` (se popula con `generate_embeddings()`).
6. Aplicar `strip_private_tags()` al texto antes de escribir.

**Comportamiento modo `legacy`:**
1. Llamar `legacy_parser.parse(filepath, doc_type="rules")`.
2. Para cada bloque: crear un `pending_proposal` con `source_type="legacy"`, `legacy_original=raw_text`.
3. Inferir campos faltantes con valores conservadores: `severity="medium"`, `category="general"`, `scope_id=default_scope_id`.
4. **No escribir a `rules`**. Solo a `pending_proposals`.
5. Aplicar `strip_private_tags()` al texto antes de escribir.

**Implementar también:** `index_lessons_from_markdown` con lógica equivalente.

### Paso 6.2 — Implementar `approve_proposal`

1. Leer `pending_proposal` por ID.
2. Generar el siguiente code via `next_rule_code()` o `next_lesson_code()`.
3. Construir el bloque atómico Markdown (formato canónico de PRD sección 3.1 o 3.2).
4. Determinar el archivo `.md` destino según `scope_id`:
   - `global-java` → `knowledge-base/global/java.md`
   - `global-quarkus` → `knowledge-base/global/quarkus.md`
   - `project-psp-integrator` → `knowledge-base/projects/psp-integrator.md`
5. Verificar que el archivo destino existe. Si no → error antes de escribir nada.
6. Append del bloque al final del archivo con `\n\n` de separación.
7. Calcular `file_offset` y `byte_length` del bloque recién escrito.
8. INSERT en `rules` o `lessons`.
9. INSERT en `rule_history` o `lesson_history` con `change_type=CREATED`.
10. Si `suggested_attributes` → INSERT en `rule_attributes`.
11. UPDATE `pending_proposals` con `status=approved`.

**Implementar también:** `edit_proposal`, `reject_proposal`, `list_pending_proposals`, `convert_to_atomic_format`, `promote_rule` — con las firmas y comportamientos exactos de la sección 5.1 del PRD.

### Paso 6.3 — Tests de integración

**Archivo:** `tests/integration/test_index_and_query.py`

Tests exactos:
1. `test_index_atomic_seed_file` — indexar `knowledge-base/global/java.md` en modo atomic → 3 reglas en DB, 3 registros en `rule_history`.
2. `test_index_reindex_no_change` — indexar el mismo archivo dos veces → `updated=0`, no duplica registros.
3. `test_index_legacy_creates_proposals` — crear un fixture legacy, indexar en modo legacy → N registros en `pending_proposals`, 0 en `rules`.
4. `test_approve_proposal_writes_md` — crear una proposal, aprobar → el bloque atómico existe al final del `.md` destino. El `file_offset` del registro en `rules` apunta al bloque correcto.
5. `test_positional_read_after_approve` — después de aprobar, leer `raw_bytes[offset:offset+length]` del `.md` → reproduce el bloque atómico exacto.

**Archivo:** `tests/integration/test_proposals_flow.py`

Tests exactos:
1. `test_edit_proposal` — crear proposal, editar texto, verificar que `proposed_text` cambió y `status` sigue `pending`.
2. `test_reject_proposal` — crear proposal, rechazar con razón → `status=rejected`, `reason` guardada.
3. `test_approve_with_attributes` — crear proposal con `suggested_attributes`, aprobar → verificar que `rule_attributes` contiene los atributos.

```bash
python -m pytest tests/integration/ -v
```

**Gate de Fase 6:** Todos los tests pasan. La lectura posicional post-aprobación reproduce exactamente el bloque atómico escrito.

---

## FASE 7 — Tools de Knowledge Consumption (query con modo SQL)

**Objetivo:** `query_rules()` funciona con filtrado SQL, `detail` y `format` params.

### Paso 7.1 — Implementar `query_rules`

**Archivo:** `src/meridian/tools/knowledge_consumption.py`

**Algoritmo exacto (modo SQL — sin `query_text`):**
1. `scopes = resolve_scope_hierarchy(conn, project_id)`
2. `attributes = load_scope_attributes(conn, project_id)`
3. SQL: `SELECT * FROM rules WHERE scope_id IN (?) AND status='active'`
4. Aplicar filtros opcionales: `AND category=?`, `AND severity=?`, `AND tags LIKE ?`
5. `filtered_ids = filter_by_attributes(conn, [r.id for r in candidates], attributes)`
6. Si `detail="summary"`: retornar solo `code, scope_id, severity, category, applies_to, tags`
7. Si `detail="full"`: para cada regla, leer texto via `file_offset + byte_length` del `.md`
8. Ordenar por precedencia: las reglas de scopes más específicos primero
9. `return serialize(results, format, fields)`

**Implementar también:** `query_lessons`, `get_rule_context`, `get_rule_timeline`, `get_project_scope_resolution`, `get_rule_audit_log` — con las firmas exactas de la sección 5.2 del PRD.

### Paso 7.2 — Tests de integración

Agregar al archivo `tests/integration/test_index_and_query.py`:

1. `test_query_rules_summary` — indexar seed, query con `detail="summary"` → response tiene `code` pero no `text`.
2. `test_query_rules_full` — query con `detail="full"` → response tiene `text` completo.
3. `test_query_rules_filter_severity` — query con `severity="critical"` → solo retorna reglas critical.
4. `test_query_rules_filter_category` — query con `category="logging"` → solo RN-JAVA-002.
5. `test_query_rules_scope_resolution` — query para `project-psp-integrator` → retorna reglas de `global-java` + `global-quarkus` + `global` + `project-psp-integrator`.
6. `test_query_rules_toon_format` — query con `format="toon"` → response empieza con `items[N]{...}:`.
7. `test_query_rules_stale_index` — modificar el `.md` externamente para que `file_offset` sea inválido → response incluye error `STALE_INDEX` para esa regla.
8. `test_get_rule_timeline` — indexar, luego update una regla → `get_rule_timeline` retorna los 2 eventos de historial.

```bash
python -m pytest tests/integration/test_index_and_query.py -v
```

**Gate de Fase 7:** Todos los tests pasan. `query_rules` retorna resultados correctos con filtrado SQL, scope resolution, attribute filtering, y serialización JSON/TOON.

---

## FASE 8 — RAG (embeddings + búsqueda semántica)

**Objetivo:** `generate_embeddings()` popula ChromaDB. `query_rules(query_text=...)` usa búsqueda semántica con fallback a SQL.

### Paso 8.1 — Crear `embedder.py`

**Archivo:** `src/meridian/rag/embedder.py`

**Responsabilidades:**
1. Cargar modelo `BAAI/bge-small-en-v1.5` via `sentence_transformers.SentenceTransformer`. El modelo se descarga automáticamente la primera vez.
2. Detección automática de device: `"mps"` en Apple Silicon, `"cuda"` si GPU NVIDIA, `"cpu"` por defecto. No requerir configuración manual.
3. Función `generate_embedding(text: str) -> list[float]` — genera un vector de 384 dimensiones.
4. Función `generate_embeddings_batch(texts: list[str]) -> list[list[float]]` — batch para eficiencia.
5. Lazy loading del modelo — solo se carga en memoria cuando se llama por primera vez.

### Paso 8.2 — Crear `vector_store.py`

**Archivo:** `src/meridian/rag/vector_store.py`

**Responsabilidades:**
1. Inicializar ChromaDB persistent client en `KNOWLEDGE_BASE_PATH/chroma/`.
2. Dos colecciones: `meridian_rules` y `meridian_lessons`.
3. Función `upsert_rule(rule_id: str, text: str, embedding: list[float], metadata: dict)` — inserta o actualiza en la colección `meridian_rules`. Metadata incluye `scope_id`, `category`, `severity`.
4. Función `search_rules(query_embedding: list[float], scope_ids: list[str], top_k: int = 20) -> list[dict]` — búsqueda semántica con filtro `where: {"scope_id": {"$in": scope_ids}}`.
5. Función `chromadb_available() -> bool`:
   - `True` si el directorio `chroma/` existe Y al menos una colección tiene documentos.
   - `False` en cualquier otro caso. No lanzar error.
6. Funciones equivalentes para lecciones.

### Paso 8.3 — Implementar `generate_embeddings` tool

**Archivo:** Agregar a `src/meridian/tools/knowledge_management.py`

1. SELECT todas las reglas/lecciones activas con `embedding_id IS NULL` (o modificadas después del último embedding).
2. Generar embeddings en batch via `embedder.generate_embeddings_batch()`.
3. Upsert en ChromaDB via `vector_store.upsert_rule()`.
4. UPDATE `rules.embedding_id` con el ID del vector en ChromaDB.
5. Retornar `{processed, skipped, errors, duration_seconds}`.

Si `scope_id` se pasa como parámetro → filtrar solo reglas de ese scope.

### Paso 8.4 — Agregar modo RAG a `query_rules`

En `knowledge_consumption.py`, agregar la rama RAG:

```python
if query_text and chromadb_available():
    query_embedding = embedder.generate_embedding(query_text)
    candidates = vector_store.search_rules(query_embedding, scopes, top_k=20)
    results = apply_metadata_filters(candidates, category, severity, tags)
else:
    # modo SQL existente (no cambiar)
    results = sqlite_filter(...)
```

La rama SQL existente no se modifica. El modo RAG es aditivo.

### Paso 8.5 — Tests

**Archivo:** `tests/unit/test_embedder.py`

1. `test_generate_embedding_dimensions` — un texto → vector de exactamente 384 dimensiones.
2. `test_generate_batch` — 3 textos → 3 vectores de 384 dimensiones.
3. `test_similar_texts_closer` — embeddings de "exception handling in Java" y "Java error management" tienen cosine similarity > 0.7. Embedding de "Flutter widget layout" tiene similarity < 0.3 con ambos.

**Archivo:** `tests/integration/test_rag_query.py`

1. `test_generate_embeddings_populates_ids` — indexar seed, generar embeddings → todas las reglas tienen `embedding_id IS NOT NULL`.
2. `test_rag_query_returns_relevant` — generar embeddings, buscar `query_text="logging structured JSON"` → RN-JAVA-002 (logging) aparece en los resultados.
3. `test_rag_fallback_to_sql` — sin embeddings generados, buscar con `query_text` → usa SQL, retorna resultados normales, sin error.
4. `test_rag_and_sql_same_results_for_exact_filter` — query con `severity="critical"` debe retornar las mismas reglas en ambos modos (puede diferir el orden).

```bash
python -m pytest tests/unit/test_embedder.py tests/integration/test_rag_query.py -v
```

**Gate de Fase 8:** Todos los tests pasan. La búsqueda semántica retorna resultados relevantes. El fallback a SQL funciona cuando no hay embeddings.

---

## FASE 9 — Tools de Audit y Extraction

**Objetivo:** Los 3 tools de audit y los 3 de extraction funcionan end-to-end.

### Paso 9.1 — Implementar audit tools

**Archivo:** `src/meridian/tools/audit_flows.py`

Implementar `audit_pr`, `analyze_pr_feedback`, `check_feature_against_rules` con los comportamientos exactos de la sección 5.3 del PRD. Cada tool:
- Llama `query_rules()` y/o `query_lessons()` internamente con `detail="full"`.
- Persiste el registro en la tabla correspondiente (`pr_audits`, `planning_checks`).
- Retorna el contexto estructurado con `instruction_for_client`.
- **No analiza ni clasifica** — solo entrega datos.

### Paso 9.2 — Implementar extraction tools

**Archivo:** `src/meridian/tools/extraction.py`

Implementar `extract_rules_from_transcript`, `extract_lessons_from_transcript`, `create_pending_proposal` con los comportamientos exactos de la sección 5.4 del PRD. Cada tool:
- Aplica `strip_private_tags()` al texto de entrada (Capa 1).
- Retorna scopes disponibles, reglas existentes, template atómico.
- `create_pending_proposal` aplica `strip_private_tags()` antes de persistir (Capa 2).
- Valida que `suggested_scope_id` exista en `scopes` antes de persistir.

### Paso 9.3 — Tests

Tests mínimos de integración para verificar que los tools:
1. Persisten registros en las tablas correctas.
2. Aplican `strip_private_tags()` en ambas capas.
3. Retornan el formato de response documentado en la sección de Request/Response del diseño.

**Gate de Fase 9:** Los 6 tools retornan responses conformes al PRD. Los registros se persisten correctamente. Los `<private>` tags nunca llegan a la DB.

---

## FASE 10 — Skill Generator

**Objetivo:** `generate_project_skills()` genera `SKILL.md` + `AGENTS.md` conformes al estándar agentskills.io.

### Paso 10.1 — Implementar `skill_generator.py`

**Archivo:** `src/meridian/utils/skill_generator.py`

1. Recibe `project_id` y `project_path`.
2. Llama `query_rules(project_id, detail="summary")` para obtener el catálogo.
3. Llama `query_rules(project_id, detail="full")` para `references/rules.md`.
4. Genera `{project_path}/.claude/skills/meridian/{project_id}/SKILL.md` con el formato exacto de la sección 5.1 del PRD (YAML frontmatter con `name`, `description`, `metadata.auto_invoke`, `metadata.allowed-tools`).
5. Genera `{project_path}/.claude/skills/meridian/{project_id}/references/rules.md` con el texto completo de las reglas.
6. Lee `{project_path}/AGENTS.md` si existe. Busca la sección `## Auto-invoke Skills (Meridian)`. Si existe, la reemplaza. Si no, la appenda al final.
7. Crea los directorios necesarios si no existen.

### Paso 10.2 — Tests

1. Verificar que `SKILL.md` generado tiene YAML frontmatter válido parseable.
2. Verificar que `AGENTS.md` contiene la tabla Auto-invoke con las 3 filas estándar.
3. Verificar que `references/rules.md` contiene el texto de todas las reglas activas.

**Gate de Fase 10:** Los archivos generados son conformes al estándar agentskills.io y contienen exactamente las reglas activas del proyecto.

---

## FASE 11 — MCP Server (FastMCP) + Seguridad

**Objetivo:** Todos los tools registrados en FastMCP. Transporte stdio y HTTP/SSE funcional. Control de acceso, token de sesión y audit log integrados.

### Paso 11.1 — Implementar `server.py` completo

**Archivo:** `src/meridian/server.py`

1. Crear instancia `FastMCP("meridian")`.
2. Registrar cada tool con `@mcp.tool()` decorator. Cada tool llama a la función correspondiente en `tools/`.
3. Al iniciar, ejecutar `initialize_db()`.

**Integración de seguridad en cada tool handler:**

Cada handler registrado en FastMCP debe seguir este patrón exacto:

```python
from meridian.utils.security import (
    check_access, AccessDeniedError, extract_safe_params,
    log_tool_access, TOOL_ACCESS_LEVELS, generate_session_token,
    validate_session_token,
)

@mcp.tool()
def approve_proposal(proposal_id: str) -> str:
    tool_name = "approve_proposal"
    log_id = next_sequential_id(conn, "access_log", "al")
    params = extract_safe_params({"proposal_id": proposal_id})
    try:
        check_access(tool_name)
        result = _approve_proposal_impl(conn, proposal_id)
        log_tool_access(conn, log_id, tool_name,
                       TOOL_ACCESS_LEVELS[tool_name], None, params,
                       "success", current_transport)
        return result
    except AccessDeniedError as e:
        log_tool_access(conn, log_id, tool_name,
                       TOOL_ACCESS_LEVELS[tool_name], None, params,
                       "denied", current_transport)
        return json.dumps({
            "error": "ACCESS_DENIED",
            "tool": e.tool_name,
            "required_level": e.required,
            "current_level": e.current,
            "message": str(e),
        })
    except Exception as e:
        log_tool_access(conn, log_id, tool_name,
                       TOOL_ACCESS_LEVELS[tool_name], None, params,
                       "error", current_transport)
        raise
```

**Restricción:** No usar un metaclass o decorador mágico que oculte la lógica de seguridad. Cada handler debe tener el patrón explícito. La razón: el desarrollador que lea el código debe ver exactamente dónde se valida el acceso y dónde se registra el log sin buscar en otra capa.

### Paso 11.2 — Implementar transporte stdio

```python
def run_stdio() -> None:
    global current_transport
    current_transport = "stdio"
    initialize_db(get_db_path())
    mcp.run(transport="stdio")
```

No se genera token de sesión. No se valida `Authorization` header. stdio es inherentemente seguro.

### Paso 11.3 — Implementar transporte HTTP/SSE con token de sesión

```python
def run_http(port: int = 8080) -> None:
    global current_transport
    current_transport = "http"
    initialize_db(get_db_path())

    session_token = generate_session_token()
    print(f"Meridian HTTP/SSE server started on 127.0.0.1:{port}")
    print(f"Session token: {session_token}")
    print(f"Include header: Authorization: Bearer {session_token}")

    # Middleware de validación de token
    # Implementación depende de FastMCP — si FastMCP expone middleware hooks,
    # usar esos. Si no, validar en cada handler HTTP antes de procesar.

    mcp.run(transport="sse", host="127.0.0.1", port=port)
    # NUNCA usar host="0.0.0.0"
```

**Validación de token:** Cada request HTTP debe incluir `Authorization: Bearer {token}`. Si falta o no coincide → responder `401 Unauthorized`. La comparación usa `secrets.compare_digest()` para prevenir timing attacks.

**Restricción crítica:** `host` siempre es `"127.0.0.1"`. Si FastMCP no soporta el parámetro `host`, configurar un proxy reverso o usar un wrapper ASGI/WSGI que lo restrinja. Documentar la solución en el README.

### Paso 11.4 — Tests de contrato y seguridad

**Archivo:** `tests/contract/test_mcp_tool_signatures.py`

Tests existentes:
1. Verificar que cada tool registrado tiene exactamente los parámetros documentados en el PRD sección 5.
2. Verificar nombres de tools, tipos de parámetros, y valores por defecto.

**Archivo:** `tests/integration/test_access_control.py` (nuevo)

Tests exactos:
1. `test_read_level_allows_query` — con `MERIDIAN_ACCESS_LEVEL=read`, invocar `query_rules` → `result="success"` en `access_log`.
2. `test_read_level_denies_approve` — con `MERIDIAN_ACCESS_LEVEL=read`, invocar `approve_proposal` → response con `ACCESS_DENIED`, `result="denied"` en `access_log`.
3. `test_write_level_allows_all` — con `MERIDIAN_ACCESS_LEVEL=write`, invocar `approve_proposal` → `result="success"`.
4. `test_access_log_records_all_invocations` — invocar 3 tools diferentes → 3 registros en `access_log` con `tool_name`, `timestamp`, `result` correctos.
5. `test_access_log_excludes_sensitive_params` — invocar `audit_pr` con `pr_diff="large diff..."` → `parameters` en `access_log` NO contiene el diff, solo `project_id`.
6. `test_default_level_is_analyze` — sin variable de entorno → tools de analyze permitidos, tools de write denegados.

```bash
python -m pytest tests/contract/ tests/integration/test_access_control.py -v
```

**Gate de Fase 11:** `python -m meridian mcp` inicia sin error. Todos los tools están registrados con las firmas correctas. El control de acceso funciona en los 3 niveles. El audit log registra todas las invocaciones. El transporte HTTP/SSE imprime el token de sesión al iniciar y solo acepta conexiones en 127.0.0.1.

---

## FASE 12 — README y documentación

**Objetivo:** Un desarrollador que no participó en el diseño puede instalar, configurar y usar Meridian siguiendo solo el README.

### Paso 12.1 — Crear `README.md`

**Contenido obligatorio:**
1. Qué es Meridian (2 párrafos, tagline incluido).
2. Instalación en macOS, Linux y Windows (comandos exactos).
3. Configuración MCP para Claude Code (JSON exacto).
4. Configuración MCP para OpenCode (JSON exacto).
5. Quick start: indexar un archivo, consultar reglas, generar skills.
6. Guía de migración de archivos legacy (`Global_Rules.md`, `learned-prd-en.md`).
7. Variables de entorno: `KNOWLEDGE_BASE_PATH`, `MERIDIAN_PROJECT_PATH`, `MERIDIAN_ACCESS_LEVEL`.
8. Seguridad: explicación de los 3 niveles de acceso con tabla de tools por nivel, token de sesión para HTTP/SSE, y cómo consultar el audit log.
9. Referencia de tools: tabla con nombre, descripción, parámetros y nivel de acceso de cada tool.

**Gate de Fase 12:** Un revisor sigue el README desde cero en una máquina limpia y logra: instalar Meridian, indexar el archivo seed, ejecutar `query_rules`, verificar que `MERIDIAN_ACCESS_LEVEL=read` deniega `approve_proposal`, y generar skills.

---

## Gate Final

Ejecutar la suite completa:

```bash
python -m pytest tests/ -v --tb=short
```

**Criterio de aprobación:**
- Todos los tests pasan en las 3 capas (unit, integration, contract).
- `python -m meridian version` imprime la versión.
- `python -m meridian mcp` inicia el servidor stdio sin error.
- Las reglas del archivo seed son consultables vía `query_rules`.
- `generate_embeddings` popula ChromaDB y `query_rules(query_text=...)` retorna resultados semánticamente relevantes.
- `generate_project_skills` genera archivos conformes al estándar agentskills.io.
- Con `MERIDIAN_ACCESS_LEVEL=read`, los tools de escritura retornan `ACCESS_DENIED`.
- Con `MERIDIAN_ACCESS_LEVEL=write`, todos los tools funcionan.
- Toda invocación de tool queda registrada en `access_log` con `result`, `tool_name` y `transport`.
- Los campos sensibles (`pr_diff`, `feedback_text`, `text`, `proposed_text`) nunca aparecen en `access_log.parameters`.
- `python -m meridian serve` imprime el session token y solo acepta conexiones en 127.0.0.1.
- No hay imports circulares entre módulos.
- `ruff check src/` reporta 0 errores.

---

*"Code drifts. Meridian doesn't."*  
*Axiom JUMA — From first principles to real-world solutions.*
