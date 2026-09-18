# Reporte Técnico Detallado – Degradación de rendimiento proporcional al crecimiento del conocimiento indexado (Axiom Meridian)

**Fecha:** 2026-06-11
**Repositorio(s):** axiom-meridian (único repositorio afectado)
**Rama / commit base:** main · a3a2f47
**Stack principal:** Python ≥3.11 · fastmcp ≥0.4.0 · SQLite (stdlib `sqlite3`, modo WAL) · chromadb ≥0.5.0 · sentence-transformers ≥3.0.0 (BAAI/bge-small-en-v1.5, 384 dim) · torch ≥2.2.0
**Audiencia:** Arquitecto de software / Tech Lead
**Tipo de análisis:** [x] Estático / [ ] Dinámico / [ ] Mixto

## 1. Resumen del hallazgo (para orientar al arquitecto)

El sistema se vuelve más lento a medida que crecen las reglas, las lecciones y el historial de uso, por cuatro mecanismos independientes que componen su costo: (1) **cada una de las 26 tools MCP** ejecuta en su camino crítico un `SELECT MAX(id) ... LIKE 'al-%'` sobre `access_log`, tabla que recibe una fila por invocación y carece de optimización de índice para ese patrón — el costo por llamada crece linealmente con el historial acumulado; (2) el filtrado por atributos dinámicos ejecuta **una consulta SQL por cada regla candidata** (N+1); (3) las consultas con `detail="full"` releen **el archivo `.md` completo una vez por cada fila** devuelta (O(reglas × tamaño de archivo)); y (4) **14 puntos del código abren una conexión SQLite nueva por operación**, repitiendo pragmas y verificaciones de filesystem. Ninguno de estos costos tiene techo: la degradación es estructural, no un bug puntual.

## 2. Descripción del problema fundamental

- **Problema estructural:** la gestión de recursos es por-operación en lugar de por-proceso: identidades secuenciales calculadas con escaneos `MAX(...) LIKE` sobre tablas que solo crecen, conexiones SQLite efímeras, lecturas de archivo completas para extraer fragmentos, y ausencia total de caché (jerarquía de scopes, atributos, contenido de archivos y disponibilidad de ChromaDB se recalculan en cada llamada).
- **Manifestación observable:** toda invocación de tool — incluidas las de solo lectura como `query_rules` — paga un escaneo de `access_log`, un `INSERT` y un `COMMIT` (fsync); las consultas `detail="full"` sobre N reglas que viven en un mismo `.md` leen ese archivo N veces; `filter_by_attributes` emite una query por regla.
- **Impacto en mantenibilidad:** el patrón de conexión es inconsistente (el servidor mantiene una conexión global pero `knowledge_management.py` abre 8 conexiones propias y `knowledge_consumption.py` 6; `query_lessons` se invoca desde `server.py:359` sin recibir la conexión compartida mientras `query_rules` sí la recibe en `server.py:333`), lo que hace difícil razonar sobre transacciones y costos.
- **Impacto en escalabilidad del equipo:** las tools de análisis (`audit_pr`, `check_feature_against_rules`) cargan **todas** las reglas y lecciones con `detail="full"` y persisten un snapshot JSON completo de las reglas en `pr_audits` por cada auditoría — el costo de auditar un PR y el tamaño de la base crecen con el total de conocimiento, no con lo relevante al PR.

## 3. Evidencia cuantitativa y cualitativa

### 3.1 Mapa de componentes afectados

| Componente | Ruta | Tipo | Dependencia problemática | ¿Usa abstracción? | Notas |
|---|---|---|---|---|---|
| `_security_pattern` | src/meridian/server.py:89-144 | Wrapper de seguridad (26 tools) | `next_sequential_id` sobre `access_log` + `COMMIT` por llamada | No | Camino crítico de **toda** invocación MCP |
| `next_sequential_id` / `next_rule_code` / `next_lesson_code` | src/meridian/utils/id_generator.py | Generación de IDs | `SELECT MAX(...) WHERE ... LIKE 'prefix-%'` | No | 15 sitios de llamada; el `LIKE` con colación BINARY por defecto no usa el índice PK |
| `filter_by_attributes` | src/meridian/utils/scope_resolver.py:63-107 | Filtro ADR-002 | Un `SELECT` por `rule_id` candidato (N+1) | No | Se ejecuta en cada `query_rules` (camino SQL y camino RAG) |
| `_read_positional_text` | src/meridian/tools/knowledge_consumption.py:21-44 | Lectura posicional | `path.read_bytes()` del archivo completo por fila | No | Invocado en bucle por `query_rules`/`query_lessons` `detail="full"`, `get_rule_context` |
| `get_connection(get_db_path())` | src/meridian/tools/knowledge_management.py (8 ocurrencias), src/meridian/tools/knowledge_consumption.py (6 ocurrencias) | Gestión de conexión | Conexión nueva + `PRAGMA journal_mode=WAL` + chequeos de filesystem por operación | No | `get_db_path()` → `get_knowledge_base_path()` hace `is_dir()`/`mkdir`/`touch` en cada llamada (src/meridian/config.py:33-48) |
| `audit_pr` / `check_feature_against_rules` | src/meridian/tools/audit_flows.py:24-25, 136-137 | Tools de análisis | `query_rules`/`query_lessons` con `detail="full"` sobre todo el proyecto + snapshot JSON en `pr_audits` | No | Costo e ingesta de disco proporcionales al total de reglas |
| `generate_embeddings` | src/meridian/tools/knowledge_management.py:1129-1267 | Indexación RAG | `collection.upsert()` de un documento a la vez en bucle | Parcial (embeddings sí van en batch) | N round-trips a ChromaDB en vez de 1 |
| `chromadb_available` | src/meridian/rag/vector_store.py:43-54 | Detección RAG | `count()` sobre 2 colecciones en cada consulta con `query_text` | No | Llamado en knowledge_consumption.py:121 y :241 |
| `get_project_scope_resolution` | src/meridian/tools/knowledge_consumption.py:444-480 | Caché de scopes | `INSERT ... ON CONFLICT` + `COMMIT` por llamada a una tabla (`project_scope_resolution`) que **ningún código lee** | No | Caché de escritura pura; `resolve_scope_hierarchy` siempre recalcula con un `SELECT` por nivel |
| Esquema SQL | src/meridian/db/schema.sql | Índices | 11 índices definidos; **0** sobre `rule_history`/`lesson_history` | — | `get_rule_timeline`, `get_rule_context` y `get_rule_audit_log` filtran por `rule_id` sobre tablas append-only sin índice |

### 3.2 Patrones repetidos (boilerplate)

Generación de ID secuencial con escaneo `MAX + LIKE` (src/meridian/utils/id_generator.py:62-72), ejecutada por las 26 tools vía `_security_pattern`:

```python
def next_sequential_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    cursor = conn.execute(
        f"SELECT MAX(id) FROM {table} WHERE id LIKE ?",  # noqa: S608
        (f"{prefix}-%",),
    )
    row = cursor.fetchone()
    max_id = row[0] if row else None
    if max_id is None:
        return f"{prefix}-0001"
    parts = max_id.rsplit("-", 1)
    next_num = int(parts[1]) + 1
    return f"{prefix}-{next_num:04d}"
```

Lectura del archivo completo para extraer un fragmento, una vez por fila (src/meridian/tools/knowledge_consumption.py:36-44):

```python
    current_size = path.stat().st_size
    if file_offset + byte_length > current_size:
        result["text"] = None
        result["error"] = "STALE_INDEX"
        return result
    raw_bytes = path.read_bytes()
    chunk = raw_bytes[file_offset : file_offset + byte_length]
    result["text"] = chunk.decode("utf-8")
```

N+1 en filtrado por atributos (src/meridian/utils/scope_resolver.py:84-90):

```python
    result: list[str] = []
    for rule_id in rule_ids:
        cursor = conn.execute(
            "SELECT key, value FROM rule_attributes WHERE rule_id = ?",
            (rule_id,),
        )
        rule_attrs = {row[0]: row[1] for row in cursor.fetchall()}
```

Apertura de conexión efímera por operación (patrón repetido en src/meridian/tools/knowledge_management.py y knowledge_consumption.py):

```python
    conn = get_connection(get_db_path())
    try:
        ...
    finally:
        conn.close()
```

- **Número de archivos con estos patrones:** 5 (`server.py`, `id_generator.py`, `scope_resolver.py`, `knowledge_consumption.py`, `knowledge_management.py`), más 2 consumidores amplificadores (`audit_flows.py`, `skill_generator.py`).
- **Número de variantes del patrón:** 4 — (a) `MAX(id) LIKE` genérico (`next_sequential_id`, 15 sitios de llamada), (b) `MAX(code) LIKE 'RN-…'`/`'LL-…'` (`next_rule_code`/`next_lesson_code`), (c) conexión efímera con `close_on_exit` opcional (knowledge_consumption acepta `conn=None`), (d) conexión efímera incondicional (knowledge_management nunca acepta conexión externa). La variante (c)/(d) es evidencia de deriva: dos convenciones de gestión de conexión coexistiendo.

### 3.3 Inconsistencias de configuración

| Configuración | Valor en módulo A | Valor en módulo B | ¿Centralizada? |
|---|---|---|---|
| Conexión SQLite | Global única, creada en `server.py:75-81` (`init_db`) y pasada a algunas tools | Efímera por operación en 14 puntos de `tools/` (`get_connection(get_db_path())`) | No |
| Paso de conexión a queries | `query_rules` recibe `conn=_get_conn()` (server.py:333) | `query_lessons` se llama **sin** `conn` (server.py:359) → abre conexión propia | No |
| `PRAGMA synchronous` | No configurado (default `FULL`) en `db/connection.py:14-19` | — (recomendado `NORMAL` con WAL) | No |
| Padding de IDs secuenciales | 3 dígitos (`RN-{TECH}-NNN`, id_generator.py:34) | 4 dígitos (`prefix-NNNN`, id_generator.py:69) | Sí (mismo archivo), pero ambos rompen el orden lexicográfico de `MAX()` al superar 999/9999 |
| Caché de resolución de scopes | Tabla `project_scope_resolution` escrita en cada `get_project_scope_resolution` | Nunca leída por `resolve_scope_hierarchy` (recalcula siempre) | No |

### 3.4 Stack tecnológico relevante

```text
Lenguaje:        Python >=3.11 (.python-version presente)
Servidor MCP:    fastmcp >=0.4.0
Base de datos:   SQLite (stdlib sqlite3), journal_mode=WAL, foreign_keys=ON
Vector store:    chromadb >=0.5.0 (PersistentClient, colecciones meridian_rules / meridian_lessons)
Embeddings:      sentence-transformers >=3.0.0, modelo BAAI/bge-small-en-v1.5 (384 dim), torch >=2.2.0
HTTP:            httpx >=0.27.0
Dev:             pytest >=8.0.0, pytest-asyncio >=0.23.0, ruff >=0.5.0
```

(Versiones extraídas de `pyproject.toml`.)

### 3.5 Limitaciones técnicas identificadas (importantes para evaluar opciones)

- **Los archivos Markdown son la fuente de verdad; SQLite es solo índice/estado** (invariante declarado en CLAUDE.md y README). Cualquier optimización de lectura debe poder demostrarse derivada del `.md` y detectar desincronización.
- **Las lecturas posicionales son frágiles por diseño:** reescribir un bloque en medio de un archivo (camino `update` de `approve_proposal`, knowledge_management.py:638, y `_mark_deprecated_in_md`, :1270) invalida silenciosamente los `file_offset` de todos los bloques posteriores del mismo archivo (debilidad conocida, documentada en CLAUDE.md). Toda opción que conserve offsets por fila hereda este costo de re-indexación.
- **El registro en `access_log` por invocación es un requisito de seguridad** (audit trail documentado en README §Audit Log), no un accesorio: las opciones pueden cambiar *cómo* se genera el ID o *cuándo* se hace el commit, pero no eliminar el registro.
- **El `LIKE` por defecto de SQLite es case-insensitive sobre colación BINARY**, lo que impide al optimizador convertir `LIKE 'prefix-%'` en un range-scan del índice — los `MAX(...) LIKE` son escaneos completos salvo que se cambie el esquema de IDs o la colación.
- **`check_same_thread=False` con conexión global compartida sin lock** (db/connection.py:16): en transporte HTTP/SSE las requests concurrentes serializan o intercalan transacciones sobre una sola conexión; cualquier opción de centralizar conexiones debe definir la estrategia de concurrencia.
- **Los códigos `RN-{TECH}-NNN` / `LL-{TECH}-NNN` son contrato del producto** (aparecen en los `.md` y en los headers de bloque que parsea `atomic_parser.py`); no se pueden reemplazar por enteros opacos. Los IDs internos (`al-`, `prop-`, `rh-`, `lh-`, `audit-`, `check-`) no aparecen en archivos Markdown.
- **Bases instaladas en campo:** `scripts/install.sh` despliega a usuarios finales; cambios de esquema requieren ruta de migración sobre `meridian.db` existentes (ya existe precedente: `db/` contiene una migración 001 para columnas de `lessons`).
- **ADR-001 obliga a que las tools de consulta retornen strings serializados** y ADR-002 fija la semántica de inclusión conservadora del filtrado por atributos — las optimizaciones no pueden alterar resultados observables.

## 4. Opciones de solución evaluadas

### Opción A – Corrección puntual de los hot paths (optimización in-place)

- **Descripción técnica:** atacar cada mecanismo de degradación en su sitio, sin alterar la arquitectura de conexiones ni el modelo de lectura. (1) Reemplazar `MAX(...) LIKE` por una tabla de contadores `id_counters(name TEXT PRIMARY KEY, next INTEGER)` actualizada atómicamente (`UPDATE ... RETURNING` o `INSERT ON CONFLICT`), conservando el formato externo de los códigos `RN-*`/`LL-*` y los prefijos internos; (2) reescribir `filter_by_attributes` como una sola query `WHERE rule_id IN (...)` agrupada en Python; (3) en `_read_positional_text`, sustituir `read_bytes()` por `seek(offset) + read(byte_length)` y añadir un caché de archivo por consulta (dict `path → bytes`) en los bucles de `detail="full"`; (4) añadir índices `rule_history(rule_id)`, `lesson_history(lesson_id)`, `pending_proposals(scope_id)`, `pr_audits(pr_ref, project_id)`; (5) `PRAGMA synchronous=NORMAL` en `get_connection`; (6) batch de `upsert` a ChromaDB en `generate_embeddings`.
- **Archivos/componentes a modificar/crear:**
  - src/meridian/utils/id_generator.py (3 funciones)
  - src/meridian/utils/scope_resolver.py (`filter_by_attributes`)
  - src/meridian/tools/knowledge_consumption.py (`_read_positional_text` y sus 2 bucles llamadores)
  - src/meridian/db/schema.sql (+1 tabla, +4 índices) y una migración nueva para bases existentes
  - src/meridian/db/connection.py (1 pragma)
  - src/meridian/tools/knowledge_management.py (`generate_embeddings`)
- **Cambios esperados en el código:**
  - Eliminación del escaneo O(n) en las 26 tools y del N+1 en los 2 caminos de `query_rules`
  - Adición de ~1 tabla, ~4 índices, ~1 script de migración; sin archivos nuevos de lógica
- **Ventajas:**
  - Elimina los tres costos que crecen sin techo (escaneo de `access_log`, N+1, relectura de archivos) con cambios localizados
  - No toca los invariantes de producto (Markdown fuente de verdad, formato de códigos, semántica ADR-001/002)
  - Cada corrección es verificable de forma aislada con la suite existente (`uv run pytest`)
- **Desventajas:**
  - No resuelve las 14 conexiones efímeras ni la inconsistencia `query_rules`/`query_lessons`; el costo fijo por operación (pragmas + chequeos de filesystem en `get_knowledge_base_path`) permanece
  - No mitiga la fragilidad de offsets (sección 3.5): `STALE_INDEX` y re-indexaciones siguen ocurriendo tras cada edición de bloque
  - La tabla de contadores introduce un punto de contención de escritura y requiere sembrarse desde los datos existentes en la migración
- **Esfuerzo estimado:** 2–3 días persona (0.5 d contadores + migración; 0.5 d N+1 e índices; 0.5 d lectura posicional; 0.5 d batch Chroma + pragma; 0.5–1 d pruebas de migración sobre bases existentes)
- **Riesgos técnicos principales:**
  - Migración de contadores: si el sembrado inicial calcula mal el máximo existente, se generan IDs duplicados (violación de PK)
  - El cambio de `synchronous` a `NORMAL` relaja garantías de durabilidad ante corte de energía (aceptable con WAL, pero es un cambio de contrato implícito)

### Opción B – Gestión centralizada de recursos: conexión única administrada + cachés en memoria invalidables

- **Descripción técnica:** introducir un módulo administrador de recursos (p. ej. `src/meridian/db/resources.py`) que posea: una conexión SQLite por proceso (o por hilo, vía `threading.local`, para el transporte HTTP/SSE) con pragmas aplicados una sola vez; cachés en memoria con invalidación explícita para (a) jerarquía de scopes y atributos de scope (cambian solo en `create_project`/seed), (b) atributos de reglas (cambian solo en `approve_proposal`), (c) resultado de `chromadb_available()` (cambia solo en `generate_embeddings`), y (d) contenido de archivos `.md` validado por `mtime` para las lecturas posicionales. Las escrituras de `access_log` pasan a usar `rowid` implícito o el contador de la Opción A, y el `COMMIT` del log se difiere a un batch (cola en memoria volcada cada N registros o al cierre). Los 14 puntos de `get_connection(get_db_path())` se reemplazan por el administrador, unificando la convención (c)/(d) de la sección 3.2.
- **Archivos/componentes a modificar/crear:**
  - src/meridian/db/resources.py [NUEVO] (administrador de conexión + cachés)
  - src/meridian/server.py (sustituir `_get_conn` y el patrón de log)
  - src/meridian/tools/knowledge_management.py (8 sustituciones de conexión + puntos de invalidación en `approve_proposal`, `create_project`, `generate_embeddings`, `index_*`)
  - src/meridian/tools/knowledge_consumption.py (6 sustituciones + uso del caché de archivos)
  - src/meridian/utils/scope_resolver.py (lectura a través del caché)
  - src/meridian/rag/vector_store.py (`chromadb_available` cacheado)
  - src/meridian/config.py (memoizar `get_knowledge_base_path` tras la primera validación)
- **Cambios esperados en el código:**
  - Eliminación de las 14 aperturas de conexión efímeras y de los chequeos de filesystem repetidos
  - Adición de 1 módulo nuevo y de puntos de invalidación en los 4 choke points de escritura
- **Ventajas:**
  - Reduce el costo fijo de **toda** operación, no solo de las consultas grandes; el camino de lectura deja de pagar escrituras síncronas por llamada
  - Resuelve la deriva de convenciones de conexión (sección 3.2, variantes c/d) con una sola abstracción
  - El caché de scopes/atributos elimina además los `SELECT` por nivel de `resolve_scope_hierarchy` en cada consulta
- **Desventajas:**
  - La invalidación de cachés es el nuevo punto de fallo: un camino de escritura que olvide invalidar produce resultados obsoletos (violación silenciosa de ADR-002); hoy los `.md` también pueden editarse fuera del proceso, lo que limita la validez del caché de archivos a la verificación por `mtime`
  - El log diferido en batch debilita el audit trail ante un crash (registros en cola se pierden) — requiere decisión explícita de seguridad
  - Mayor superficie de cambio: toca los 5 archivos del mapa 3.1 simultáneamente; concurrencia HTTP/SSE exige definir conexión-por-hilo y pruebas específicas que hoy no existen
- **Esfuerzo estimado:** 5–7 días persona (1.5 d administrador + sustituciones; 1 d cachés e invalidación; 1 d log en batch + decisión de durabilidad; 1.5–2.5 d pruebas de concurrencia e integración)
- **Riesgos técnicos principales:**
  - Stale cache tras escrituras externas a los `.md` (editores humanos) — el caché por `mtime` mitiga pero la granularidad de `mtime` puede ocultar ediciones en el mismo segundo
  - Regresión de aislamiento transaccional al compartir una conexión entre tools que hoy asumen conexión propia (commits intercalados)

### Opción C – Lectura servida desde el índice: SQLite como caché materializada del Markdown, validada por archivo

- **Descripción técnica:** invertir el camino de lectura sin invertir la fuente de verdad. Las columnas `rules.text` y `lessons.what_happened` **ya almacenan** el texto completo (se escriben en `index_*` y `approve_proposal`); esta opción sirve `detail="full"` desde SQLite y degrada la verificación posicional por-fila a una verificación de frescura por-archivo: una tabla `indexed_files(file_path, mtime, content_hash)` se coteja una vez por consulta (un `stat()` por archivo, no un `read_bytes()` por fila); si el archivo cambió, la consulta responde `STALE_INDEX` a nivel de archivo y se exige re-indexación (que ya existe: `index_rules_from_markdown` es idempotente por `code`). Los `file_offset`/`byte_length` se conservan exclusivamente como metadato de escritura para `approve_proposal`/`_mark_deprecated_in_md`. Complementariamente, el filtrado de tags por `LIKE '%tag%'` (4 ocurrencias, sección 3.2) se reemplaza por una tabla normalizada `rule_tags(rule_id, tag)` indexada. Incluye además los puntos (1), (2) y (4) de la Opción A, que son ortogonales.
- **Archivos/componentes a modificar/crear:**
  - src/meridian/tools/knowledge_consumption.py (`_read_positional_text` → verificación por archivo; `query_rules`, `query_lessons`, `get_rule_context`)
  - src/meridian/db/schema.sql (+`indexed_files`, +`rule_tags`/`lesson_tags`, +índices de historial) y migración con backfill desde `rules.tags`/`lessons.tags`
  - src/meridian/tools/knowledge_management.py (`index_*` y `approve_proposal` actualizan `indexed_files` y las tablas de tags)
  - src/meridian/utils/id_generator.py y src/meridian/utils/scope_resolver.py (puntos ortogonales heredados de la Opción A)
- **Cambios esperados en el código:**
  - Eliminación de las relecturas O(filas × tamaño de archivo) y de los 4 `LIKE '%…%'` no indexables
  - Adición de 2–3 tablas, su backfill y la lógica de frescura por archivo
- **Ventajas:**
  - El costo de `detail="full"` pasa de proporcional al tamaño de los `.md` a proporcional al número de filas devueltas; `audit_pr`/`check_feature_against_rules` (los consumidores más pesados, sección 3.1) son los principales beneficiados
  - Reduce el radio de impacto de la fragilidad de offsets: una edición de bloque ya no produce `STALE_INDEX` silencioso por fila sino una señal explícita por archivo, accionable con re-indexación
  - El filtrado por tags se vuelve exacto (hoy `LIKE '%go%'` matchea substrings) e indexado
- **Desventajas:**
  - Es la mayor desviación conceptual: la lectura deja de "tocar" el `.md` en cada consulta, y la garantía de fidelidad pasa a depender de la disciplina de actualización de `indexed_files` en todos los caminos de escritura (internos y externos)
  - Duplicación efectiva del texto (ya existe hoy, pero esta opción la consagra como camino de lectura oficial) — el arquitecto debe validar que no contradice el espíritu del invariante "SQLite es solo índice"
  - Migración con backfill de tags y hashes de archivos sobre bases en campo; mayor esfuerzo de pruebas (la suite de integración valida hoy el comportamiento posicional, p. ej. tests/integration/test_index_and_query.py)
- **Esfuerzo estimado:** 6–9 días persona (1 d frescura por archivo; 1.5 d tablas de tags + backfill; 1 d puntos ortogonales de la Opción A; 1 d actualización de caminos de escritura; 1.5–2.5 d adaptación de la suite + pruebas de migración; 0.5–1 d documentación del cambio de contrato `STALE_INDEX`)
- **Riesgos técnicos principales:**
  - Desincronización silenciosa si un camino de escritura (o una edición manual del `.md` no seguida de re-indexación) no refresca `indexed_files` — el hash por archivo mitiga, pero solo se verifica al consultar
  - Cambio observable del contrato de error: `STALE_INDEX` pasa de granularidad fila a granularidad archivo; consumidores existentes del MCP podrían depender del comportamiento actual

### Tabla comparativa unificada

| Criterio | Opción A | Opción B | Opción C |
|---|---|---|---|
| Elimina la degradación O(historial) por llamada (`access_log`) | ✅ | ✅ | ✅ (hereda A) |
| Elimina el N+1 de atributos | ✅ | ✅ (vía caché) | ✅ (hereda A) |
| Elimina la relectura de archivo por fila en `detail="full"` | Parcial (seek + caché por consulta; sigue habiendo I/O por consulta) | Parcial (caché por `mtime`; primera consulta paga lectura completa) | ✅ (lectura desde SQLite) |
| Reduce el costo fijo por operación (conexiones, pragmas, filesystem) | ❌ | ✅ | ❌ (salvo lo heredado de A) |
| Mitiga la fragilidad de offsets / `STALE_INDEX` | ❌ | ❌ | Parcial (granularidad archivo, señal explícita) |
| Acoplamiento resultante entre tools y recursos | Sin cambio (alto: cada tool gestiona su conexión) | Bajo (abstracción única) | Sin cambio (alto) |
| Facilidad de testing | Alta (cambios aislados, suite actual aplica) | Media (requiere pruebas de concurrencia e invalidación nuevas) | Media (requiere adaptar suite de lecturas posicionales) |
| Escalabilidad a >10.000 reglas / archivos `.md` grandes | Media (I/O de archivo sigue en el camino de lectura) | Media-alta (depende del hit-rate del caché) | Alta (lectura indexada, tags exactos) |
| Riesgo de resultados obsoletos | Nulo | Medio (invalidación de caché) | Medio (frescura por archivo) |
| Requiere migración de esquema en bases instaladas | Sí (1 tabla, 4 índices) | Sí (la de A) | Sí (2–3 tablas + backfill) |
| Esfuerzo (días persona) | 2–3 | 5–7 | 6–9 |
| Riesgo en producción | Bajo | Medio | Medio |

Las opciones no son mutuamente excluyentes en su totalidad: A es subconjunto funcional de C en los puntos (1), (2) y (4), y B es componible con cualquiera de las otras dos. Se documentan por separado porque atacan mecanismos de degradación distintos y el arquitecto puede secuenciarlas.

## 5. Restricciones de diseño inamovibles

- Los archivos Markdown permanecen como única fuente de verdad del conocimiento; SQLite y ChromaDB son derivados reconstruibles (invariante de producto, CLAUDE.md / README).
- El registro de auditoría en `access_log` por invocación de tool no puede eliminarse (requisito de seguridad documentado en README §Audit Log); solo puede cambiar su mecánica interna.
- Los códigos visibles `RN-{TECH}-NNN` / `LL-{TECH}-NNN` y las etiquetas de campo en español de los bloques atómicos (`**Regla:**`, `**Qué pasó:**`, etc.) son contrato del formato de archivo y no pueden cambiar.
- Las tools de consulta deben seguir retornando strings serializados en `json`/`toon` (ADR-001) y la semántica de inclusión conservadora del filtrado por atributos debe preservarse exactamente (ADR-002).
- `strip_private_tags` debe permanecer en todo camino de escritura (garantía de privacidad Layer 2).
- Debe existir ruta de migración para las bases `meridian.db` ya desplegadas vía `scripts/install.sh` (no se puede asumir reinstalación limpia).
- Stack fijo en SQLite stdlib + ChromaDB + sentence-transformers; no se contempla introducir un motor de base de datos externo.

## 6. Anexo técnico

### 6.1 Árbol de archivos afectados por opción

**Opción A**

```text
src/meridian/utils/id_generator.py                    [MODIFICAR]
src/meridian/utils/scope_resolver.py                  [MODIFICAR]
src/meridian/tools/knowledge_consumption.py           [MODIFICAR]
src/meridian/tools/knowledge_management.py            [MODIFICAR]
src/meridian/db/schema.sql                            [MODIFICAR]
src/meridian/db/connection.py                         [MODIFICAR]
src/meridian/db/migrations/00X-id-counters.sql        [NUEVO]
```

**Opción B**

```text
src/meridian/db/resources.py                          [NUEVO]
src/meridian/server.py                                [MODIFICAR]
src/meridian/tools/knowledge_management.py            [MODIFICAR]
src/meridian/tools/knowledge_consumption.py           [MODIFICAR]
src/meridian/utils/scope_resolver.py                  [MODIFICAR]
src/meridian/rag/vector_store.py                      [MODIFICAR]
src/meridian/config.py                                [MODIFICAR]
tests/integration/test_concurrency.py                 [NUEVO]
```

**Opción C**

```text
src/meridian/tools/knowledge_consumption.py           [MODIFICAR]
src/meridian/tools/knowledge_management.py            [MODIFICAR]
src/meridian/db/schema.sql                            [MODIFICAR]
src/meridian/db/migrations/00X-read-index.sql         [NUEVO]
src/meridian/utils/id_generator.py                    [MODIFICAR]  (heredado de A)
src/meridian/utils/scope_resolver.py                  [MODIFICAR]  (heredado de A)
tests/integration/test_index_and_query.py             [MODIFICAR]
```

### 6.2 Fragmentos de código representativos

Cómo se ve hoy el camino crítico de toda invocación (src/meridian/server.py:96-111, abreviado):

```python
    c = _get_conn()
    log_id = next_sequential_id(c, "access_log", "al")   # SELECT MAX(id) LIKE 'al-%' → full scan
    params = extract_safe_params(params_dict)
    try:
        check_access(tool_name)
        result = impl_callable()
        log_tool_access(                                  # INSERT + COMMIT (fsync) por llamada
            c, log_id, tool_name, TOOL_ACCESS_LEVELS[tool_name],
            project_id, params, "success", current_transport,
        )
```

Caché de escritura pura — se escribe en cada llamada pero nunca se lee (src/meridian/tools/knowledge_consumption.py:461-472):

```python
        resolved_scopes_json = json.dumps(scopes)
        conn.execute(
            """
            INSERT INTO project_scope_resolution (project_id, resolved_scopes)
            VALUES (?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                resolved_scopes = excluded.resolved_scopes,
                updated_at = datetime('now')
            """,
            (project_id, resolved_scopes_json),
        )
        conn.commit()
```

Upsert a ChromaDB de un documento por iteración (src/meridian/tools/knowledge_management.py:1177-1189, abreviado):

```python
        for idx, row in enumerate(rule_rows):
            ...
            vector_store.upsert_rule(
                rule_id=rule_id,
                text=row_dict["text"],
                embedding=embeddings[idx],
                metadata={...},
            )
```

### 6.3 Resultados de análisis automático (si existe)

No disponible. El repositorio no incluye herramientas de profiling ni de complejidad (no hay configuración de `radon`, `py-spy`, `pytest-benchmark` ni métricas de producción). Conteos reproducibles obtenidos por búsqueda estática en este análisis:

- Tools MCP registradas (`@mcp.tool()` en server.py): **26**
- Sitios de llamada a `next_sequential_id(`: **15**
- Aperturas de conexión efímera `get_connection(get_db_path())` en `tools/`: **14** (8 en knowledge_management.py, 6 en knowledge_consumption.py)
- Ocurrencias de `read_bytes()` en `src/`: **7**
- Ocurrencias de `conn.commit()` en `src/`: **16**
- Queries con `LIKE`: **6** (2 `MAX(code) LIKE`, 4 filtros de tags `LIKE '%…%'`)
- Índices en schema.sql: **11**; índices sobre `rule_history`/`lesson_history`: **0**

Para cuantificar en runtime se podría usar `pytest-benchmark` sobre `query_rules` con bases sintéticas de 10²–10⁴ reglas, y `EXPLAIN QUERY PLAN` sobre los `MAX(...) LIKE`.

## 7. Instrucciones para el arquitecto (lo que se espera de él)

El arquitecto debe:

1. Elegir **UNA** de las opciones (A, B o C) — o una secuencia explícita de ellas, dado que se documentó su componibilidad — basándose en criterios de bajo acoplamiento, mantenibilidad a 5 años y riesgo.
2. Justificar su decisión citando evidencia de este reporte (secciones 3.1–3.5 y tabla comparativa de la sección 4).
3. Describir los trade-offs frente a las alternativas descartadas, en particular: durabilidad del audit trail (Opción B) y granularidad del contrato `STALE_INDEX` (Opción C).
4. Generar un diagrama Mermaid de la arquitectura objetivo de gestión de recursos (conexiones, cachés y camino de lectura).
5. Autoevaluar los tres riesgos más probables de su diseño y proponer mitigaciones, considerando las restricciones inamovibles de la sección 5 (especialmente la migración de bases instaladas en campo).
