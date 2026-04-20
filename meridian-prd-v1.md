# Axiom Meridian — Product Requirements Document v1.3

**Tagline:** Code drifts. Meridian doesn't.  
**Suite:** Axiom JUMA · Product 3  
**Status:** Approved for scaffolding  
**Date:** 2026-04-19  
**Author:** Axiom JUMA

> **Cambios v1.1:** RAG incluido en V1. Soporte cross-platform Mac/Linux/Windows. Meridian autónomo — sin dependencia de herramientas externas.
>
> **Cambios v1.2:** Severidades unificadas en inglés. ADR-001 actualizado. `lesson_history` agregado. `inherits_from` y `tech_stack` eliminados del schema. `get_rule_timeline()` especificado. `query_text` en firmas de query. IDs documentados. Inserts iniciales explícitos. `chromadb_available()` definido. Parser legacy descarta "Skill Suggestions". uv + `pip install .`. `MERIDIAN_PROJECT_PATH`. Estructura con `pyproject.toml`.
>
> **Cambios v1.3:** Seguridad: control de acceso por nivel de operación (`MERIDIAN_ACCESS_LEVEL` — read/analyze/write), token de sesión para HTTP/SSE, bind exclusivo 127.0.0.1, tabla `access_log` con audit trail, `security.py` con decorator `@log_access`. Schema actualizado a 13 tablas.

---

## 1. Contexto del Sistema

Meridian es un MCP Server en Python (FastMCP) que centraliza conocimiento técnico institucional — reglas de negocio, lecciones aprendidas y transcripciones de reuniones — y lo hace disponible on-demand durante el ciclo de desarrollo de software.

El sistema resuelve un problema concreto: a medida que `Global_Rules.md` y `Lessons_Learned.md` crecen, el agente AI debe leer todo el contexto en cada sesión, degradando la velocidad y la precisión. Meridian entrega solo el conocimiento relevante para la tarea en curso, sin cargar archivos completos.

### Fuentes de conocimiento centralizadas

- **Reglas de negocio técnicas** — convenciones, restricciones y decisiones de arquitectura del equipo
- **Lecciones aprendidas** — incidentes, causas raíz y resoluciones documentadas
- **Transcripciones de reuniones** — fuente de entrada para extracción asistida por el cliente LLM

### Jerarquía de scopes

```
GLOBAL
├── global              → aplica a todos los proyectos
├── global-java         → todos los proyectos Java
│   ├── global-quarkus  → proyectos Quarkus específicamente
│   └── global-spring-boot
├── global-nestjs       → todos los proyectos NestJS
├── global-go           → todos los proyectos Go
│   ├── global-go-fiber
│   └── global-go-gin
└── global-flutter      → todos los proyectos Flutter

PROJECT
├── psp-integrator      → hereda global-quarkus
│   attributes: framework=quarkus, component_role=gateway, runtime=java-21
├── pac-module          → hereda global-nestjs
│   attributes: framework=nestjs, component_role=last-mile
└── ledger              → hereda global-flutter
    attributes: framework=flutter, component_role=mobile-client
```

Los scopes son **dinámicos** — se gestionan via `scope_attributes` (ADR-002). Agregar un nuevo framework o rol arquitectónico requiere solo un `INSERT`, nunca un `ALTER TABLE`.

---

## 2. Arquitectura de Archivos

**El Markdown es la fuente de verdad. SQLite es el índice y el estado. Nunca al revés.**

```
KNOWLEDGE_BASE_PATH/          ← variable de entorno, ruta externa al repo
├── knowledge-base/
│   ├── global/
│   │   ├── general.md
│   │   ├── java.md
│   │   ├── quarkus.md
│   │   ├── nestjs.md
│   │   ├── go.md
│   │   └── flutter.md
│   └── projects/
│       ├── psp-integrator.md
│       ├── pac-module.md
│       └── ledger.md
├── lessons/
│   ├── global/
│   │   ├── java.md
│   │   └── nestjs.md
│   └── projects/
│       ├── psp-integrator.md
│       ├── pac-module.md
│       └── ledger.md
└── meridian.db               ← SQLite, colocated con los .md
```

---

## 3. Formatos de Markdown

### 3.1 Formato atómico de reglas (canónico)

Cada regla es un bloque independiente parseable por `file_offset + byte_length`:

```markdown
## RN-JAVA-011
**Scope:** global-java
**Categoría:** exception-handling
**Severidad:** critical
**Aplica a:** **/*.java
**Tags:** exceptions, resilience, timeout
**Fuente:** postmortem-2026-01-14
**Regla:** Todo cliente HTTP externo debe configurar timeout explícito
de conexión (3s) y lectura (10s). La ausencia de timeout es causa
de thread starvation en producción.
```

**Campos obligatorios:** `Scope`, `Categoría`, `Severidad`, `Aplica a`, `Tags`, `Fuente`, `Regla`  
**Severidades válidas:** `critical`, `high`, `medium`, `low`

### 3.2 Formato atómico de lecciones (canónico)

```markdown
## LL-PSP-003
**Scope:** project-psp-integrator
**Proyecto:** psp-integrator
**Fecha:** 2026-01-14
**Severidad del impacto:** critical
**Área afectada:** payment-processing
**Tags:** timeout, resilience, thread-starvation
**Qué pasó:** Timeout no manejado en llamada al PSP externo
causó acumulación de threads bloqueados en producción.
**Impacto:** Degradación del servicio de pagos durante 40 minutos.
**Causa raíz:** RestTemplate sin timeout explícito en cliente HTTP.
**Resolución:** Implementar Resilience4j con connectionTimeout=3s,
readTimeout=10s y fallback a error 503.
**Originó regla:** RN-JAVA-011
```

**Campos obligatorios:** todos los listados arriba  
**Severidades válidas:** `critical`, `high`, `medium`, `low` (unificado con reglas)

### 3.3 Formato legacy (migración)

Los archivos existentes (`Global_Rules.md`, `learned-prd-en.md`) usan formato narrativo con secciones `###` y bullets `- **Campo**: valor`. El parser de Meridian soporta este formato via `mode="legacy"` en los tools de indexación. **El modo legacy nunca escribe directamente a `rules` o `lessons` — todo pasa por `pending_proposals`.**

---

## 4. Schema SQLite

```sql
-- Scopes jerárquicos
scopes (
  id          TEXT PRIMARY KEY,   -- "global-java", "project-psp-integrator"
  type        TEXT NOT NULL,       -- "global" | "project"
  name        TEXT NOT NULL,
  parent_id   TEXT REFERENCES scopes(id)
)

-- Atributos dinámicos de scope (ADR-002)
scope_attributes (
  scope_id  TEXT NOT NULL REFERENCES scopes(id) ON DELETE CASCADE,
  key       TEXT NOT NULL,         -- "framework", "component_role", "runtime_version"
  value     TEXT NOT NULL,         -- "quarkus", "gateway", "java-21"
  PRIMARY KEY (scope_id, key)
)

-- Reglas técnicas
rules (
  id                  TEXT PRIMARY KEY,
  scope_id            TEXT NOT NULL REFERENCES scopes(id),
  code                TEXT NOT NULL UNIQUE,  -- "RN-JAVA-011"
  text                TEXT NOT NULL,
  category            TEXT NOT NULL,
  severity            TEXT NOT NULL,         -- "critical"|"high"|"medium"|"low"
  applies_to          TEXT,                  -- glob pattern
  tags                TEXT,                  -- JSON array
  status              TEXT DEFAULT 'active', -- "active"|"deprecated"|"pending"
  source_type         TEXT,                  -- "transcript"|"pr-feedback"|"manual"|"legacy"
  source_ref          TEXT,                  -- "postmortem-2026-01-14", "PR-16"
  file_path           TEXT,
  file_offset         INTEGER,
  byte_length         INTEGER,
  originated_lesson_id TEXT REFERENCES lessons(id),
  embedding_id        TEXT,                  -- ID del vector en ChromaDB; NULL hasta generate_embeddings()
  created_at          TEXT DEFAULT (datetime('now')),
  updated_at          TEXT DEFAULT (datetime('now'))
)

-- Atributos dinámicos de reglas (ADR-002)
rule_attributes (
  rule_id   TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  key       TEXT NOT NULL,
  value     TEXT NOT NULL,
  PRIMARY KEY (rule_id, key)
)

-- Historial de cambios de reglas (append-only)
rule_history (
  id            TEXT PRIMARY KEY,
  rule_id       TEXT NOT NULL REFERENCES rules(id),
  change_type   TEXT NOT NULL,  -- "CREATED"|"UPDATED"|"DEPRECATED"|"PROMOTED"
  previous_text TEXT,
  new_text      TEXT,
  reason        TEXT,
  triggered_by  TEXT,           -- "PR-16", "LL-PSP-001", "prop-0041"
  changed_at    TEXT DEFAULT (datetime('now'))
)

-- Historial de cambios de lecciones (append-only, simplificado)
lesson_history (
  id            TEXT PRIMARY KEY,
  lesson_id     TEXT NOT NULL REFERENCES lessons(id),
  change_type   TEXT NOT NULL,  -- "CREATED"|"DEPRECATED" (solo dos estados)
  reason        TEXT,
  triggered_by  TEXT,
  changed_at    TEXT DEFAULT (datetime('now'))
)

-- Lecciones aprendidas
lessons (
  id                TEXT PRIMARY KEY,
  scope_id          TEXT NOT NULL REFERENCES scopes(id),
  code              TEXT NOT NULL UNIQUE,  -- "LL-PSP-003"
  project           TEXT,
  date_occurred     TEXT,
  severity          TEXT,                  -- "critical"|"high"|"medium"|"low"
  area_affected     TEXT,
  what_happened     TEXT,
  impact            TEXT,
  root_cause        TEXT,
  resolution        TEXT,
  tags              TEXT,                  -- JSON array
  originated_rule_id TEXT REFERENCES rules(id),
  status            TEXT DEFAULT 'active',
  file_path         TEXT,
  file_offset       INTEGER,
  byte_length       INTEGER,
  embedding_id      TEXT                  -- ID del vector en ChromaDB; NULL hasta generate_embeddings()
)

-- Vínculos bidireccionales regla ↔ lección
rule_lesson_links (
  rule_id   TEXT NOT NULL REFERENCES rules(id),
  lesson_id TEXT NOT NULL REFERENCES lessons(id),
  link_type TEXT NOT NULL,  -- "ORIGINATED_FROM" | "REFINED_BY" | "RELATED"
  PRIMARY KEY (rule_id, lesson_id)
)

-- Cache de resolución de scopes
project_scope_resolution (
  project_id      TEXT PRIMARY KEY,
  resolved_scopes TEXT NOT NULL,  -- JSON array ordenado por precedencia
  updated_at      TEXT DEFAULT (datetime('now'))
)

-- Registro de auditorías de PR
pr_audits (
  id               TEXT PRIMARY KEY,
  project_id       TEXT NOT NULL,
  pr_ref           TEXT,
  diff_hash        TEXT,
  rules_evaluated  INTEGER,
  violations_found TEXT,           -- JSON array de clasificaciones
  feedback_analyzed TEXT,
  rule_version_snapshot TEXT,      -- JSON: estado de cada regla en el momento del audit
  audited_at       TEXT DEFAULT (datetime('now'))
)

-- Registro de checks de planning
planning_checks (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL,
  feature_description TEXT,
  conflicts_found     TEXT,         -- JSON array de clasificaciones
  rules_involved      TEXT,         -- JSON array de rule_ids
  checked_at          TEXT DEFAULT (datetime('now'))
)

-- Propuestas pendientes de aprobación
pending_proposals (
  id                   TEXT PRIMARY KEY,
  type                 TEXT NOT NULL,    -- "rule" | "lesson"
  scope_id             TEXT REFERENCES scopes(id),
  proposed_text        TEXT NOT NULL,
  metadata             TEXT,             -- JSON: campos parciales del bloque atómico
  suggested_attributes TEXT,             -- JSON array de {key, value}
  source_type          TEXT,             -- "transcript"|"legacy"|"pr-feedback"|"manual"
  source_ref           TEXT,
  status               TEXT DEFAULT 'pending', -- "pending"|"approved"|"rejected"
  reason               TEXT,
  legacy_original      TEXT,             -- texto original del bloque legacy (para auditoría)
  created_at           TEXT DEFAULT (datetime('now'))
)

-- Registro de acceso a tools (audit trail de seguridad)
access_log (
  id          TEXT PRIMARY KEY,
  timestamp   TEXT DEFAULT (datetime('now')),
  tool_name   TEXT NOT NULL,
  access_level TEXT NOT NULL,       -- "read" | "analyze" | "write"
  project_id  TEXT,
  parameters  TEXT,                 -- JSON de params (sin contenido sensible)
  result      TEXT NOT NULL,        -- "success" | "denied" | "error"
  transport   TEXT                  -- "stdio" | "http"
)

-- Índices para rendimiento
CREATE INDEX idx_rules_scope_id ON rules(scope_id);
CREATE INDEX idx_rules_severity ON rules(severity);
CREATE INDEX idx_rules_category ON rules(category);
CREATE INDEX idx_rules_status ON rules(status);
CREATE INDEX idx_scope_attributes_key_value ON scope_attributes(key, value);
CREATE INDEX idx_rule_attributes_key_value ON rule_attributes(key, value);
CREATE INDEX idx_lessons_scope_id ON lessons(scope_id);
CREATE INDEX idx_pending_proposals_status ON pending_proposals(status);
CREATE INDEX idx_access_log_timestamp ON access_log(timestamp);
CREATE INDEX idx_access_log_tool_name ON access_log(tool_name);
```

### 4.1 Estrategia de IDs

Todas las tablas usan **prefijo + secuencial**. El prefijo indica el tipo de entidad:

| Entidad | Patrón | Ejemplo |
|---|---|---|
| Reglas | `RN-{TECH}-{NNN}` | `RN-JAVA-011` |
| Lecciones | `LL-{PROJECT}-{NNN}` | `LL-PSP-003` |
| Propuestas | `prop-{NNNN}` | `prop-0041` |
| Auditorías PR | `audit-{NNNN}` | `audit-0089` |
| Planning checks | `check-{NNNN}` | `check-0031` |
| Rule history | `rh-{NNNN}` | `rh-0001` |
| Lesson history | `lh-{NNNN}` | `lh-0001` |
| Access log | `al-{NNNN}` | `al-0001` |

El contador secuencial por prefijo se mantiene en SQLite via `MAX()` + 1 sobre el código existente. Para reglas y lecciones, `{TECH}` y `{PROJECT}` se infieren del `scope_id`.

### 4.2 Inserts iniciales de scopes

Al inicializar la DB, Meridian crea los scopes base con sus atributos:

```sql
-- Scopes globales
INSERT INTO scopes VALUES ('global',              'global', 'Global',              NULL);
INSERT INTO scopes VALUES ('global-java',         'global', 'Global Java',         'global');
INSERT INTO scopes VALUES ('global-quarkus',      'global', 'Global Quarkus',      'global-java');
INSERT INTO scopes VALUES ('global-spring-boot',  'global', 'Global Spring Boot',  'global-java');
INSERT INTO scopes VALUES ('global-nestjs',       'global', 'Global NestJS',       'global');
INSERT INTO scopes VALUES ('global-go',           'global', 'Global Go',           'global');
INSERT INTO scopes VALUES ('global-go-fiber',     'global', 'Global Go Fiber',     'global-go');
INSERT INTO scopes VALUES ('global-go-gin',       'global', 'Global Go Gin',       'global-go');
INSERT INTO scopes VALUES ('global-flutter',      'global', 'Global Flutter',      'global');

-- Scopes de proyecto
INSERT INTO scopes VALUES ('project-psp-integrator', 'project', 'PSP Integrator',  'global-quarkus');
INSERT INTO scopes VALUES ('project-pac-module',     'project', 'PAC Module',      'global-nestjs');
INSERT INTO scopes VALUES ('project-ledger',         'project', 'Ledger',          'global-flutter');

-- Atributos de proyecto
INSERT INTO scope_attributes VALUES ('project-psp-integrator', 'framework',      'quarkus');
INSERT INTO scope_attributes VALUES ('project-psp-integrator', 'component_role', 'gateway');
INSERT INTO scope_attributes VALUES ('project-psp-integrator', 'runtime_version','java-21');
INSERT INTO scope_attributes VALUES ('project-pac-module',     'framework',      'nestjs');
INSERT INTO scope_attributes VALUES ('project-pac-module',     'component_role', 'last-mile');
INSERT INTO scope_attributes VALUES ('project-ledger',         'framework',      'flutter');
INSERT INTO scope_attributes VALUES ('project-ledger',         'component_role', 'mobile-client');

-- Atributos de scope global
INSERT INTO scope_attributes VALUES ('global-java',        'framework', 'java');
INSERT INTO scope_attributes VALUES ('global-quarkus',     'framework', 'quarkus');
INSERT INTO scope_attributes VALUES ('global-spring-boot', 'framework', 'spring-boot');
INSERT INTO scope_attributes VALUES ('global-nestjs',      'framework', 'nestjs');
INSERT INTO scope_attributes VALUES ('global-go',          'framework', 'go');
INSERT INTO scope_attributes VALUES ('global-go-fiber',    'framework', 'go-fiber');
INSERT INTO scope_attributes VALUES ('global-go-gin',      'framework', 'go-gin');
INSERT INTO scope_attributes VALUES ('global-flutter',     'framework', 'flutter');
```

### 4.3 Disponibilidad de ChromaDB

`chromadb_available()` retorna `True` cuando se cumplen dos condiciones:
1. El directorio `KNOWLEDGE_BASE_PATH/chroma/` existe
2. Al menos una regla o lección tiene `embedding_id IS NOT NULL`

Si ChromaDB no está disponible, `query_rules()` usa filtrado SQL automáticamente — sin error, sin advertencia. La transición entre modos es transparente.

---

## 5. Herramientas del MCP

El retrieval tiene dos modos: filtrado SQL por metadata (siempre disponible) y búsqueda semántica via ChromaDB (activo después de `generate_embeddings()`). Ambos modos coexisten — `query_text` determina cuál se usa en cada llamada. Las firmas de los tools no cambian entre modos.

### 5.1 Knowledge Management

#### `index_rules_from_markdown(filepath, default_scope_id, mode="atomic")`

Lee un archivo Markdown e indexa sus reglas en SQLite.

- **`mode="atomic"`** — parser canónico. Lee bloques `## RN-XXX-NNN` con frontmatter estructurado. El campo `**Scope:**` del bloque tiene precedencia sobre `default_scope_id`. Si el bloque no declara scope, usa `default_scope_id`. Si el scope declarado no existe en `scopes`, registra error en el bloque y continúa con los demás.
- **`mode="legacy"`** — parser de migración. Lee secciones `###` con bullets `- **Campo**: valor` (formato `Global_Rules.md`). Extrae los campos disponibles, infiere los faltantes con valores conservadores, y crea entradas en `pending_proposals` con `source_type="legacy"` y `legacy_original` preservado. **Nunca escribe directo a `rules`.** Secciones de tipo "Skill Suggestions" (ej. `/pr-implement`, `/pr-verify`, `/pr-feedback`) son **descartadas silenciosamente** — no son reglas ni lecciones.
- Calcula `file_offset` y `byte_length` por cada bloque en modo atómico.
- Registra `change_type = CREATED` o `UPDATED` en `rule_history`.
- Deja `embedding_id = NULL`.

**Response incluye:** `indexed`, `created`, `updated`, `by_scope`, `errors`, `warnings`

#### `index_lessons_from_markdown(filepath, default_scope_id, mode="atomic")`

Idéntico al anterior pero para lecciones. Soporta `mode="legacy"` para el formato `learned-prd-en.md` (secciones `### Issue X.Y`).

#### `convert_to_atomic_format(filepath, default_scope_id, doc_type)`

Tool de migración asistida. Lee un archivo en formato legacy y genera bloques atómicos canónicos como `pending_proposals`. El usuario revisa y aprueba cada propuesta antes de que se escriba al `.md` destino.

- `doc_type`: `"rules"` | `"lessons"`
- Preserva `legacy_original` en cada propuesta para auditoría
- Infiere scope desde el contenido cuando es posible; marca como `suggested` cuando no es determinista
- Sugiere el archivo `.md` destino correcto según el scope inferido
- **Nunca escribe archivos directamente**

**Caso de uso:** migrar `Global_Rules.md` → ~40-50 `pending_proposals` → revisión humana → `approve_proposal()` → bloques atómicos en `knowledge-base/global/quarkus.md`, etc.

#### `list_pending_proposals(project_id?, type?, status?)`

Muestra propuestas filtrables por proyecto, tipo (`rule`|`lesson`) y estado (`pending`|`approved`|`rejected`).

#### `approve_proposal(proposal_id)`

1. Lee el `pending_proposal`
2. Genera el código siguiente disponible (`RN-JAVA-NNN`)
3. Escribe el bloque atómico al `.md` destino del `scope_id`
4. Calcula `file_offset` y `byte_length`
5. Inserta en `rules` o `lessons` con `status = active`
6. Registra en `rule_history` con `change_type = CREATED`
7. Si `suggested_attributes` existe → inserta en `rule_attributes`
8. Actualiza `pending_proposal.status = approved`

Si el `.md` destino no existe → error antes de escribir nada. Sin escritura parcial.

#### `edit_proposal(proposal_id, new_text, metadata?)`

Actualiza `proposed_text` y opcionalmente los campos de metadata. El `status` permanece `pending`.

#### `reject_proposal(proposal_id, reason?)`

Actualiza `status = rejected` con razón opcional. Sin efectos secundarios.

#### `promote_rule(rule_id, new_scope_id)`

Mueve una regla a un scope más general. Registra `PROMOTED` en `rule_history`. Marca la entrada original como `deprecated` en el `.md` fuente.

#### `generate_project_skills(project_id, project_path?)`

Genera los archivos del estándar agentskills.io para el proyecto.

`project_path` determina dónde se escriben los archivos. Resolución: si `project_path` se pasa explícitamente, usa ese valor. Si no, usa la variable de entorno `MERIDIAN_PROJECT_PATH`. Si tampoco existe, retorna error indicando que se necesita el path.

```
.claude/skills/meridian/{project_id}/
├── SKILL.md          ← catálogo liviano con metadata de reglas activas
└── references/
    └── rules.md      ← texto completo de las reglas resueltas
```

El `SKILL.md` generado incluye:
- `name`, `description`, `metadata.auto_invoke`, `metadata.allowed-tools`
- Tabla de reglas activas con `code`, `scope`, `severity`, `category`
- Referencia a `references/rules.md` para contenido completo

Actualiza `AGENTS.md` del proyecto con la sección Auto-invoke:

```markdown
## Auto-invoke Skills (Meridian)
| Action | Skill |
|--------|-------|
| Implementing any new feature | `meridian-{project_id}` |
| Before submitting a PR | `meridian-{project_id}` |
| Receiving Tech Lead feedback | `meridian-{project_id}` |
```

Compatible con Claude Code, OpenCode, Cursor y cualquier cliente que lea `.claude/skills/`.

---

### 5.2 Knowledge Consumption

#### `query_rules(project_id, category?, severity?, tags?, query_text?, format?, detail?)`

1. Resuelve jerarquía de scopes via `get_project_scope_resolution()`
2. Carga `scope_attributes` del proyecto
3. Filtra `rules` en SQLite por scopes resueltos + filtros opcionales
4. Evalúa `rule_attributes` de cada candidata (AND logic). Sin atributos → incluye siempre. Atributo desconocido → inclusión conservadora
5. Lee texto via `file_offset + byte_length` (solo si `detail="full"`)
6. Ordena: proyecto > tecnología > global
7. Serializa según `format`

**Parámetros:**
- `format`: `"json"` (default) | `"toon"` (opt-in, ADR-001)
- `detail`: `"summary"` (default — solo metadata, ~50 tokens/regla) | `"full"` (texto completo via lectura posicional)
- `query_text`: `string | None` — si se provee y ChromaDB tiene embeddings, activa búsqueda semántica (RAG). Sin él, se usa filtrado SQL puro.

**Error `STALE_INDEX`:** si `file_offset` supera el tamaño actual del archivo (`.md` modificado externamente), retorna error parcial con sugerencia de re-indexar.

#### `query_lessons(project_id, area?, tags?, query_text?, format?, detail?)`

Idéntico a `query_rules()` pero sobre `lessons`. Mismos parámetros `format`, `detail` y `query_text`.

#### `get_rule_timeline(rule_id)`

Retorna historial cronológico de una regla sin cargar el texto completo. Es la Capa 2 del patrón Progressive Disclosure — entre el catálogo (Capa 1) y el contexto completo (Capa 3).

Response: `{rule_code, scope, severity, category, history_events: [{change_type, reason, triggered_by, changed_at}], linked_lessons_summary: [{code, area, severity}]}`

#### `get_rule_context(rule_id)`

Retorna: regla completa (texto via lectura posicional) + historial completo (`rule_history`) + lecciones vinculadas (texto via lectura posicional). Es la Capa 3 del patrón Progressive Disclosure.

#### `get_project_scope_resolution(project_id)`

Retorna los scopes efectivos del proyecto en orden de precedencia con sus `scope_attributes`. Cacheable en `project_scope_resolution`.

#### `get_rule_audit_log(project_id?, scope_id?, since?)`

Retorna cronología de cambios en `rule_history`: reglas creadas, modificadas, promovidas o deprecadas. Incluye `deprecated_rules` con `superseded_by` cuando aplica.

---

### 5.3 Audit Flows

Los tools de audit **no analizan ni clasifican**. Resuelven el conocimiento relevante y lo entregan al cliente LLM junto con el contexto de análisis. El cliente LLM hace el razonamiento.

#### `audit_pr(pr_diff, project_id)`

1. Llama `query_rules(project_id, detail="full")` internamente
2. Llama `query_lessons(project_id, detail="full")` internamente
3. Calcula `diff_hash`
4. Persiste en `pr_audits` con `rule_version_snapshot` (estado de cada regla en el momento del audit — garantía de integridad histórica)
5. Retorna al cliente: `{audit_id, pr_diff, rules, lessons, instruction_for_client}`

`rule_version_snapshot` es un JSON con el estado de cada regla evaluada en el momento del audit. Si la regla cambia posteriormente, el registro histórico del audit permanece íntegro.

#### `analyze_pr_feedback(feedback_text, pr_ref, project_id)`

1. Busca `pr_audit` asociado a `pr_ref`
2. Retorna al cliente: `{feedback_text, rules_that_applied, pr_audit_record, instruction_for_client}`

El cliente LLM clasifica cada punto de feedback como: `RULE_VIOLATION` | `RULE_GAP` | `RULE_CONFLICT` | `STYLE_ONLY`.

#### `check_feature_against_rules(feature_description, project_id)`

1. Llama `query_rules()` + `query_lessons()` internamente
2. Persiste en `planning_checks`
3. Retorna al cliente: `{feature_description, rules, lessons, check_id, instruction_for_client}`

El cliente LLM clasifica: `HARD_CONFLICT` | `SOFT_CONFLICT` | `CONSIDERATION`.

---

### 5.4 Extraction

Los tools de extracción entregan contexto estructurado al cliente LLM. El cliente analiza y propone. Meridian valida y persiste en `pending_proposals`.

#### `extract_rules_from_transcript(text, project_id)`

Retorna al cliente LLM:
- Texto limpio (con `<private>` tags eliminados)
- Scopes disponibles para el proyecto con `scope_attributes` y `scope_selection_criteria`
- Reglas existentes en el scope (para detección de duplicados)
- Template del formato atómico canónico

El cliente LLM analiza, identifica candidatos y llama a `create_pending_proposal()` por cada uno. Meridian valida que `suggested_scope_id` exista antes de persistir.

#### `extract_lessons_from_transcript(text, project_id)`

Idéntico al anterior pero para lecciones aprendidas.

#### `create_pending_proposal(type, proposed_text, suggested_scope_id, suggested_attributes?, source_type, source_ref?)`

Tool auxiliar que el cliente LLM llama para registrar cada candidato identificado en una transcripción o análisis de feedback.

---

## 6. Privacidad y Seguridad

### 6.1 `<private>` Tags — Contrato de privacidad

El contrato de privacidad se aplica en **dos capas**:

**Capa 1 — Tool handler:** antes de retornar cualquier response al cliente LLM, el texto de entrada (transcripciones, feedback) se sanitiza:
```python
PRIVATE_PATTERN = re.compile(r'<private>.*?</private>', re.DOTALL)
clean_text = PRIVATE_PATTERN.sub('[REDACTED]', text)
```

**Capa 2 — Store:** antes de cualquier escritura en SQLite o Markdown, el texto propuesto se sanitiza nuevamente. Doble garantía: ningún dato sensible llega al almacenamiento permanente.

**Uso:**
```markdown
Endpoint PSP staging: https://api.psp-staging.com/v2/devices
<private>API key staging: sk-psp-xxx</private>
Timeout esperado: 3s
```

El campo `<private>` es eliminado antes de que el contenido llegue a Meridian.

### 6.2 Control de acceso por nivel de operación

Cada tool de Meridian tiene un nivel de acceso asignado. La variable de entorno `MERIDIAN_ACCESS_LEVEL` determina qué operaciones puede ejecutar un cliente conectado.

**Niveles:**

| Nivel | Descripción | Cuándo usarlo |
|-------|-------------|---------------|
| `read` | Solo consultas. No persiste nada. | Agentes que solo consumen conocimiento |
| `analyze` | Lectura + persistencia de registros de auditoría y propuestas | Sesiones de desarrollo normales |
| `write` | Full. Modifica la knowledge-base, aprueba propuestas, genera embeddings | Administración y migración |

**Clasificación de tools:**

```
read:
  query_rules, query_lessons, get_rule_context,
  get_rule_timeline, get_project_scope_resolution,
  get_rule_audit_log, list_pending_proposals

analyze:
  audit_pr, analyze_pr_feedback,
  check_feature_against_rules,
  extract_rules_from_transcript,
  extract_lessons_from_transcript,
  create_pending_proposal

write:
  index_rules_from_markdown, index_lessons_from_markdown,
  convert_to_atomic_format, approve_proposal,
  edit_proposal, reject_proposal, promote_rule,
  generate_embeddings, generate_project_skills
```

**Comportamiento:**
- Si `MERIDIAN_ACCESS_LEVEL` no está definida → default: `analyze`
- Valores válidos: `read`, `analyze`, `write`
- Un nivel superior incluye todos los inferiores: `write` incluye `analyze` y `read`
- Si un tool de nivel superior se invoca con nivel insuficiente → error `ACCESS_DENIED` con mensaje que indica el nivel requerido

**Response de denegación:**
```json
{
  "error": "ACCESS_DENIED",
  "tool": "approve_proposal",
  "required_level": "write",
  "current_level": "read",
  "message": "Tool 'approve_proposal' requires access level 'write'. Current level: 'read'. Set MERIDIAN_ACCESS_LEVEL=write to enable."
}
```

### 6.3 Seguridad del transporte HTTP/SSE

El transporte stdio es inherentemente seguro — solo el proceso padre puede comunicarse con el servidor. Las siguientes medidas aplican exclusivamente al transporte HTTP/SSE.

**Bind exclusivo a localhost:**

```python
# server.py — NUNCA usar host="0.0.0.0"
mcp.run(transport="sse", host="127.0.0.1", port=port)
```

El servidor HTTP/SSE solo acepta conexiones desde `127.0.0.1`. No es accesible desde otros dispositivos en la red.

**Token de sesión:**

Al iniciar en modo HTTP/SSE, Meridian genera un token aleatorio de sesión y lo imprime en stdout:

```python
import secrets
SESSION_TOKEN = secrets.token_urlsafe(32)
```

El token se incluye en el output de inicio:
```
Meridian HTTP/SSE server started on 127.0.0.1:8080
Session token: <token>
Include header: Authorization: Bearer <token>
```

Cada request HTTP debe incluir `Authorization: Bearer <token>`. Requests sin token o con token inválido reciben `401 Unauthorized`. El token cambia en cada reinicio del servidor — no se persiste.

En transporte stdio, el token no se genera ni se valida.

### 6.4 Audit log de acceso

Toda invocación de tool se registra en la tabla `access_log` del schema SQLite (sección 4). El registro incluye:

- `tool_name` — qué tool se invocó
- `access_level` — nivel requerido del tool
- `project_id` — contexto del proyecto (si aplica)
- `parameters` — JSON de los parámetros de entrada. **Restricción:** nunca incluir `pr_diff`, `feedback_text`, `text` ni `proposed_text` en el log — solo parámetros de metadata (`project_id`, `scope_id`, `severity`, `format`, `detail`). Contenido sensible se excluye siempre.
- `result` — `success`, `denied` o `error`
- `transport` — `stdio` o `http`

**Implementación:** un decorator `@log_access` se aplica a cada handler de tool. El decorator registra la invocación antes de ejecutar el tool y actualiza el `result` después.

```python
def log_access(tool_name: str, access_level: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            params = extract_safe_params(kwargs)  # excluye contenido sensible
            log_id = next_sequential_id(conn, "access_log", "al")
            # INSERT con result="pending"
            try:
                result = func(*args, **kwargs)
                # UPDATE result="success"
                return result
            except AccessDeniedError:
                # UPDATE result="denied"
                raise
            except Exception:
                # UPDATE result="error"
                raise
        return wrapper
    return decorator
```

---

## 7. Progressive Disclosure — 3 Capas

Recuperación eficiente en tokens. El cliente LLM paga el costo completo solo cuando lo necesita.

| Capa | Tool | Tokens aprox. | Uso |
|------|------|----------------|-----|
| 1 — Catálogo | `query_rules(detail="summary")` | ~50/regla | Saber qué reglas aplican |
| 2 — Contexto | `get_rule_timeline(rule_id)` | ~200/regla | Historial y evolución de una regla |
| 3 — Completo | `get_rule_context(rule_id)` | ~400/regla | Texto completo + historial + lecciones |

Las tres capas están implementadas en V1. Con RAG activo, Capa 1 puede usar búsqueda semántica en lugar de filtrado SQL — sin cambiar la firma del tool.

---

## 8. Principios de Implementación

1. **El Markdown es siempre la fuente de verdad.** SQLite es índice y estado. Nunca al revés.

2. **Nada se escribe sin aprobación explícita del usuario.** Toda extracción — incluyendo migración de archivos legacy — va a `pending_proposals` primero.

3. **La lectura de archivos es posicional** via `file_offset` y `byte_length`. Nunca se carga un archivo completo en memoria durante consultas.

4. **La jerarquía de scopes se resuelve** via `project_scope_resolution` antes de cualquier consulta. Las reglas más específicas tienen mayor peso.

5. **Toda regla tiene trazabilidad:** qué reunión la originó, qué PR la refinó, qué lección la motivó, qué versión tenía en el momento de cada audit.

6. **`embedding_id` conecta SQLite con ChromaDB.** `query_rules()` y `query_lessons()` usan búsqueda semántica cuando `embedding_id` está poblado, y filtrado SQL como fallback cuando no lo está. La firma externa no cambia en ningún caso.

7. **Los scopes y atributos son dinámicos** (ADR-002). Agregar un nuevo framework o rol arquitectónico requiere `INSERT` en `scope_attributes`, nunca `ALTER TABLE`.

8. **El formato de respuesta es configurable** (ADR-001). `format="json"` es el default en V1. `format="toon"` disponible como opt-in para reducción de tokens.

9. **Meridian no razona. El cliente LLM razona.** Los tools de audit y extracción entregan contexto estructurado. La clasificación, el análisis y las propuestas las hace el modelo que consume Meridian.

10. **`rule_version_snapshot` en `pr_audits`** garantiza integridad histórica. Si una regla cambia después de un audit, el registro del audit refleja el estado en el momento en que ocurrió.

11. **Acceso controlado por nivel de operación.** Cada tool tiene un nivel asignado (`read`, `analyze`, `write`). `MERIDIAN_ACCESS_LEVEL` determina qué operaciones acepta el servidor. Toda invocación se registra en `access_log`. El transporte HTTP/SSE requiere token de sesión y solo acepta conexiones desde `127.0.0.1`.

---

## 9. RAG — Búsqueda Semántica en V1

Meridian incluye búsqueda semántica desde la primera versión. El retrieval tiene dos modos que coexisten:

```
Modo SQL (siempre disponible):
  query_rules() → filtrado por scope + metadata en SQLite
  → funciona desde el primer indexado, sin configuración adicional

Modo RAG (activo después de generate_embeddings()):
  query_rules() → búsqueda semántica en ChromaDB + filtro de scope
  → mayor precisión para queries en lenguaje natural
  → fallback automático a SQL si embedding_id es NULL
```

El modo activo lo determina la presencia de `embedding_id` en cada regla. No hay flag de configuración — la transición es incremental regla por regla.

### 9.1 Stack de embeddings

```
sentence-transformers        ← generación de embeddings
chromadb                     ← vector store local, sin servidor externo
```

**Modelo por defecto:** `BAAI/bge-small-en-v1.5`
- Tamaño: ~130MB descargado, ~200MB en memoria
- Dimensiones: 384
- Soporte multilingüe: inglés + español (relevante para reglas en español)
- Backend: CPU en todos los sistemas; MPS en Mac Apple Silicon (automático)

**Compatibilidad cross-platform:**

| Platform | Backend de inferencia | Notas |
|---|---|---|
| macOS Apple Silicon | MPS (GPU unificada) | Auto-detectado por PyTorch |
| macOS Intel | CPU | Sin aceleración hardware |
| Linux (x86_64) | CPU o CUDA si hay GPU | CUDA opcional, no requerido |
| Windows (x86_64) | CPU o CUDA si hay GPU | CUDA opcional, no requerido |

sentence-transformers detecta el backend disponible automáticamente. Meridian no requiere configuración adicional por plataforma.

**Rendimiento estimado en CPU (sin GPU):**

| Modelo | Reglas/segundo | RAM |
|---|---|---|
| `bge-small-en-v1.5` | ~150-300 | ~200MB |
| `all-MiniLM-L6-v2` | ~300-500 | ~150MB |

Para una knowledge-base inicial de ~200 reglas, `generate_embeddings()` tarda menos de 2 minutos en CPU estándar. Re-indexado incremental (solo reglas nuevas o modificadas) es prácticamente instantáneo.

### 9.2 Arquitectura de datos RAG

ChromaDB persiste localmente en `KNOWLEDGE_BASE_PATH`:

```
KNOWLEDGE_BASE_PATH/
├── meridian.db          ← SQLite (metadata, offsets, estado)
├── chroma/              ← ChromaDB persistent client
│   ├── rules/           ← colección de embeddings de reglas
│   └── lessons/         ← colección de embeddings de lecciones
└── knowledge-base/      ← Markdown (fuente de verdad)
```

SQLite es la fuente de verdad de metadata. ChromaDB es el índice semántico. Si ChromaDB se corrompe o se elimina, `generate_embeddings()` lo reconstruye desde SQLite + los `.md`.

### 9.3 Tool: `generate_embeddings(scope_id?)`

Genera o actualiza embeddings para reglas y lecciones activas.

- Sin `scope_id` → procesa todas las reglas y lecciones activas
- Con `scope_id` → procesa solo el scope especificado (incremental)
- Solo procesa entradas con `embedding_id = NULL` o modificadas desde el último embedding
- Actualiza `embedding_id` en SQLite al completar cada entrada
- Persiste en ChromaDB con metadata de scope para filtrado híbrido

**Response:** `{processed, skipped, errors, duration_seconds}`

### 9.4 Modo híbrido en `query_rules()` y `query_lessons()`

```python
# Lógica interna — la firma del tool no cambia
def query_rules(project_id, category=None, severity=None,
                tags=None, query_text=None, format="json", detail="summary"):

    scopes = resolve_scope_hierarchy(project_id)

    if query_text and chromadb_available():
        # RAG: búsqueda semántica con filtro de scope
        candidates = chroma_search(query_text, scopes, top_k=20)
        results = apply_metadata_filters(candidates, category, severity, tags)
    else:
        # SQL: filtrado por metadata (siempre disponible como fallback)
        results = sqlite_filter(scopes, category, severity, tags)

    return serialize(results, format, detail)
```

`query_text` es el parámetro opcional que activa el modo RAG. Sin él, el comportamiento es idéntico al modo SQL puro.

### 9.5 Extensión futura — V2

Cuando el volumen de reglas supere los ~1000 elementos o se requiera búsqueda multilingüe más precisa:

- Migrar a modelo más capaz: `BAAI/bge-m3` (567M params, 100+ idiomas)
- Evaluación de vector stores alternativos: LanceDB, Qdrant local
- Clustering semántico de reglas para detección de redundancias

Estas mejoras no requieren cambios en los tools ni en el schema SQLite.

---

## 10. Transporte y Compatibilidad de Plataformas

Meridian expone dos transportes simultáneos:

- **stdio** — para Claude Code y OpenCode via configuración MCP estándar
- **HTTP/SSE** — para otros clientes en localhost

```json
// Claude Code — ~/.claude/settings.json
{
  "mcpServers": {
    "meridian": {
      "command": "python",
      "args": ["-m", "meridian", "mcp"],
      "env": { "KNOWLEDGE_BASE_PATH": "/ruta/a/meridian-kb" }
    }
  }
}

// OpenCode — opencode.json
{
  "mcp": {
    "meridian": {
      "type": "local",
      "command": ["python", "-m", "meridian", "mcp"],
      "env": { "KNOWLEDGE_BASE_PATH": "{env:KNOWLEDGE_BASE_PATH}" }
    }
  },
  "permission": {
    "mcp": { "meridian": "ask" }
  }
}
```

### Soporte cross-platform

Meridian es compatible con macOS, Linux y Windows sin configuración adicional por plataforma.

| Platform | `KNOWLEDGE_BASE_PATH` ejemplo | Notas |
|---|---|---|
| macOS | `/Users/abel/meridian-kb` | MPS disponible en Apple Silicon |
| Linux | `/home/abel/meridian-kb` | CUDA opcional si hay GPU NVIDIA |
| Windows | `C:\Users\abel\meridian-kb` | Usa `\` o `/` — Python los normaliza |

**Requisitos comunes:**
- Python 3.11+
- `KNOWLEDGE_BASE_PATH` debe existir y tener permisos de lectura/escritura
- `MERIDIAN_PROJECT_PATH` — ruta al proyecto del usuario (para `generate_project_skills()`). Opcional — si no se define, el tool requiere `project_path` como parámetro explícito
- `MERIDIAN_ACCESS_LEVEL` — nivel de acceso: `read`, `analyze`, `write`. Default: `analyze`. Ver sección 6.2
- SQLite incluido en stdlib de Python — sin instalación adicional
- ChromaDB usa almacenamiento local en `KNOWLEDGE_BASE_PATH/chroma/` — sin servidor externo

**Hardware de referencia:** Mac Mini M4 (10 núcleos, 16GB RAM). El MCP server consume ~50MB RAM en modo SQL. Con RAG activo (~200MB adicionales por el modelo de embedding). Compatible con hardware equivalente en Linux y Windows.

---

## 11. Stack

```
# Core — requerido en todas las plataformas
Python 3.11+
FastMCP                    ← MCP server framework
SQLite (sqlite3 stdlib)    ← sin dependencias externas de DB
httpx                      ← HTTP client (stub para GitHub API)

# RAG — requerido en V1
sentence-transformers      ← generación de embeddings locales
chromadb                   ← vector store local, sin servidor externo
torch                      ← backend de inferencia (CPU por defecto)
                              MPS en Apple Silicon, CUDA opcional en Linux/Windows
```

No hay dependencias de servicios externos. Todo corre localmente.

**Gestor de dependencias:** `uv` — rápido, cross-platform, compatible con `pyproject.toml`.

**Instalación:**
```bash
git clone https://github.com/axiom-juma/meridian.git
cd meridian
uv pip install .
# o alternativamente:
pip install .
```

Meridian se instala como paquete Python local (`pip install .`). El `pyproject.toml` declara todas las dependencias incluyendo RAG.

---

## 12. Decisiones de Arquitectura Registradas

| ADR | Decisión | Estado |
|-----|----------|--------|
| ADR-001 | Formato de serialización de respuestas: JSON default, TOON opt-in | Accepted |
| ADR-002 | Atributos dinámicos de scopes y reglas via tablas EAV | Accepted |
| ADR-003 (pendiente) | Integración con CLAUDE.md / AGENTS.md — reemplazo del patrón de contexto estático | Pending |
| ADR-004 (pendiente) | Estrategia de testing: unit, integration, contract, snapshot | Pending |

---

## 13. Scaffolding — Entregables V1

```
meridian/                          ← repo root
├── pyproject.toml                 ← dependencias, metadata, entry point `python -m meridian`
├── README.md                      ← setup cross-platform, configuración MCP, guía de migración
├── src/
│   └── meridian/
│       ├── __init__.py            ← versión del paquete
│       ├── __main__.py            ← entry point para `python -m meridian mcp` y `python -m meridian serve`
│       ├── server.py              ← FastMCP, registro de tools, transporte stdio + HTTP/SSE,
│       │                             bind 127.0.0.1, token de sesión (HTTP), @log_access decorator
│       ├── config.py              ← KNOWLEDGE_BASE_PATH, MERIDIAN_PROJECT_PATH,
│       │                             MERIDIAN_ACCESS_LEVEL, detección de plataforma
│       ├── db/
│       │   ├── __init__.py
│       │   ├── schema.sql         ← schema completo + inserts iniciales de scopes
│       │   ├── connection.py      ← gestión de conexión SQLite, inicialización de DB
│       │   └── migrations/        ← migraciones futuras
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── knowledge_management.py  ← index, convert, approve, edit, reject, promote,
│       │   │                               generate_skills, generate_embeddings
│       │   ├── knowledge_consumption.py ← query_rules, query_lessons, get_rule_context,
│       │   │                               get_rule_timeline, get_scope_resolution, get_audit_log
│       │   ├── audit_flows.py           ← audit_pr, analyze_pr_feedback, check_feature_against_rules
│       │   └── extraction.py            ← extract_rules_from_transcript, extract_lessons_from_transcript,
│       │                                   create_pending_proposal
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── atomic_parser.py   ← parser modo "atomic": bloques ## RN-XXX-NNN
│       │   └── legacy_parser.py   ← parser modo "legacy": secciones ### con bullets
│       ├── rag/
│       │   ├── __init__.py
│       │   ├── embedder.py        ← carga de modelo, generación de embeddings, detección backend
│       │   └── vector_store.py    ← cliente ChromaDB, colecciones rules/lessons, búsqueda semántica
│       └── utils/
│           ├── __init__.py
│           ├── serializers.py     ← json_encode(), toon_encode() — ADR-001
│           ├── privacy.py         ← strip_private_tags() — dos capas
│           ├── security.py        ← access level validation, @log_access decorator,
│           │                         session token generation, extract_safe_params()
│           ├── scope_resolver.py  ← resolución de jerarquía + filtrado por atributos — ADR-002
│           ├── id_generator.py    ← generación de IDs prefijo + secuencial
│           └── skill_generator.py ← generate_project_skills() → SKILL.md + AGENTS.md
├── tests/
│   ├── unit/
│   │   ├── test_atomic_parser.py
│   │   ├── test_legacy_parser.py
│   │   ├── test_scope_resolver.py
│   │   ├── test_serializers.py
│   │   ├── test_privacy.py
│   │   ├── test_security.py
│   │   ├── test_id_generator.py
│   │   └── test_embedder.py
│   ├── integration/
│   │   ├── test_index_and_query.py
│   │   ├── test_proposals_flow.py
│   │   └── test_rag_query.py      ← valida modo SQL, modo RAG, y fallback
│   └── contract/
│       └── test_mcp_tool_signatures.py
└── knowledge-base/                ← archivos de ejemplo para validar parser (no se instala)
    └── global/
        └── java.md                ← 3 reglas en formato atómico (seed inicial)
```

### Prioridad de implementación en el scaffolding

1. `pyproject.toml` + `__main__.py` + `__init__.py` — estructura de paquete instalable
2. Schema SQL + `connection.py` — inicialización de DB con inserts de scopes y `scope_attributes`
3. `id_generator.py` — generación de IDs prefijo + secuencial
4. `atomic_parser.py` + `legacy_parser.py` con extracción de `file_offset`/`byte_length`
5. `privacy.py` — strip `<private>` tags en dos capas
6. `scope_resolver.py` con soporte de `rule_attributes` (AND logic, inclusión conservadora)
7. `serializers.py` — `json_encode()` + `toon_encode()`
8. `index_rules_from_markdown()` — modos atomic y legacy
9. `query_rules()` con `detail`, `format` y `query_text` params (modo SQL primero)
10. `rag/embedder.py` + `rag/vector_store.py` — integración ChromaDB
11. `generate_embeddings()` — populado de `embedding_id`
12. `query_rules()` modo RAG — búsqueda semántica con fallback SQL
13. `get_rule_timeline()` — Capa 2 del Progressive Disclosure
14. `convert_to_atomic_format()` — migración asistida
15. `generate_project_skills()` — SKILL.md + AGENTS.md
16. `server.py` — registro de todos los tools en FastMCP, transporte stdio + HTTP/SSE
17. Esqueleto de todos los tools restantes con `NotImplementedError` documentado
18. `knowledge-base/global/java.md` con 3 reglas atómicas extraídas de `Global_Rules.md` real
19. README con setup cross-platform (Mac/Linux/Windows), configuración MCP para Claude Code y OpenCode, y guía de migración de archivos legacy

---

## 14. Herramientas del Ecosistema

Meridian es autónomo. No depende de ninguna herramienta externa para funcionar. Las siguientes herramientas son compatibles y pueden usarse opcionalmente junto a Meridian, pero su ausencia no afecta ninguna funcionalidad del sistema.

| Herramienta | Rol cuando está presente | Dependencia |
|---|---|---|
| **Engram** | Memoria episódica de sesión — el `source_ref` de Meridian puede referenciar un `observation_id` de Engram para trazabilidad cruzada | ❌ Opcional |
| **GitNexus** | Análisis estructural del codebase — blast radius antes de implementar. Complementa `audit_pr()` pero no es requerido | ❌ Opcional |
| **Agent Teams Lite** | Orquestación de sub-agents — el patrón de `extract_rules_from_transcript()` puede orquestarse con sub-agents especializados | ❌ Opcional |
| **Prowler Skills** | Referencia de implementación del estándar agentskills.io — `generate_project_skills()` sigue este estándar | ❌ Referencia |

**Principio:** Meridian arranca, indexa, consulta, audita y genera skills sin que ninguna de estas herramientas esté instalada.

---

*"Code drifts. Meridian doesn't."*  
*Axiom JUMA — From first principles to real-world solutions.*
