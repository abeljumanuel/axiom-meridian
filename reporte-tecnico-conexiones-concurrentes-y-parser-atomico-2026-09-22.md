# Reporte Técnico Detallado – Concurrencia de conexiones SQLite y robustez del parser atómico

**Fecha:** 2026-09-22
**Repositorio(s):** axiom-meridian (único repositorio)
**Rama / commit base:** main · 367c0a3
**Stack principal:** Python 3.11+, fastmcp ≥0.4.0, sqlite3 (stdlib, WAL), chromadb ≥0.5.0, sentence-transformers ≥3.0.0, torch ≥2.2.0
**Audiencia:** Arquitecto de software / Tech Lead
**Tipo de análisis:** [x] Estático / [ ] Dinámico / [ ] Mixto

> Nota de alcance: este reporte cubre **dos problemas relacionados** encontrados por el usuario al desplegar el servidor en su ambiente de prueba. Se documentan juntos porque comparten componente raíz (la capa de persistencia/parseo de `src/meridian/`) y porque el usuario pidió una única decisión arquitectónica que cubra ambas situaciones. Las secciones 2 a 4 están subdivididas en **Problema A (conexiones concurrentes)** y **Problema B (robustez del parser atómico)**.

---

## 1. Resumen del hallazgo (para orientar al arquitecto)

El usuario reportó que (A) no podía actualizar una Global Rule con más de una conexión SQLite abierta al tiempo, y (B) no logró indexar los registros de la base de conocimiento hasta modificar el parser atómico. La investigación del código en `main` (antes de los ajustes del usuario) confirma una causa arquitectónica concreta para A (conexiones SQLite abiertas de forma independiente en 14 puntos del código, sin `busy_timeout` ni commit explícito de la transacción del log de auditoría) y una causa **plausible pero no confirmada** para B (el segmento `{TECH}` de un ID puede contener dígitos si el `scope_id` termina en un token alfanumérico, lo cual el regex original del parser no admite, produciendo un indexado silencioso de 0 bloques sin error visible). El ajuste que el usuario aplicó a `connection.py` es válido; el aplicado a `atomic_parser.py` contiene una regex que no compila (paréntesis desbalanceado) y una lista de campos incompleta que puede corromper el texto de lecciones (`LL-*`).

## 2. Descripción del problema fundamental

### 2.1 Problema A — Conexiones SQLite concurrentes

- **Problema estructural:** el servidor mantiene una conexión SQLite global de larga duración (`server.py::conn`, vía `_get_conn()`), pero 14 puntos distintos de `tools/knowledge_management.py` y `tools/knowledge_consumption.py` abren **cada uno su propia conexión independiente** con `get_connection(get_db_path())` en cada invocación de tool, en vez de reutilizar la conexión global o un pool centralizado.
- **Manifestación observable:** `_security_pattern` (server.py) asigna el `log_id` del `access_log` con `next_sequential_id(c, ...)`, que ejecuta un `UPDATE ... RETURNING` sobre la conexión global — esto abre una transacción implícita (el módulo `sqlite3` de Python no usa autocommit por defecto). Si esa transacción no se cierra antes de que `impl_callable()` abra su propia conexión y también intente escribir, la segunda conexión choca con la primera.
- **Impacto en mantenibilidad:** no existe un único lugar donde se gestione el ciclo de vida de una conexión de escritura; cualquier tool nuevo que siga el patrón existente (`conn = get_connection(get_db_path())`) puede reintroducir la misma colisión.
- **Impacto en escalabilidad:** el problema empeora con más clientes MCP concurrentes o con el transporte HTTP/SSE (`meridian serve`), y también entre procesos distintos (CLI `python -m meridian ...` corriendo junto al servidor), ya que ambos abren conexiones independientes al mismo archivo `$KNOWLEDGE_BASE_PATH/meridian.db`.

### 2.2 Problema B — Robustez del parser atómico

- **Problema estructural:** el regex que detecta el inicio de un bloque atómico (`_BLOCK_HEADER_RE` en `parsers/atomic_parser.py`) exige que el segmento `{TECH}` del ID sea exclusivamente `[A-Z]+` (letras mayúsculas, sin dígitos), pero el generador de IDs (`utils/id_generator.py::_extract_segment`) no impone esa misma restricción al derivar `{TECH}` de un `scope_id` — puede producir segmentos alfanuméricos.
- **Manifestación observable:** si `_BLOCK_HEADER_RE.finditer(text)` no encuentra ningún match en un archivo no vacío, `parse()` retorna `blocks=[]`, `warnings=[]` sin ningún error. `index_rules_from_markdown`/`index_lessons_from_markdown` simplemente reportan `indexed: 0` — un fallo silencioso, difícil de diagnosticar sin inspeccionar el código.
- **Impacto en mantenibilidad:** el ajuste que el usuario aplicó para resolverlo (`_BLOCK_HEADER_RE` con paréntesis desbalanceado) no compila — `re.compile()` lanza `re.error` al importar el módulo, lo cual rompe el arranque de todo el servidor, no solo el indexado (reproducido en la sección 3.2).
- **Impacto en escalabilidad del equipo:** el nuevo conjunto `_KNOWN_FIELD_NAMES` (parte del mismo ajuste) solo contempla los 6 campos de **reglas**; los 5 campos adicionales de **lecciones** (`Impacto`, `Causa raíz`, `Resolución`, `Originó regla`, y el propio `Qué pasó`) no están cubiertos, por lo que cada bloque `LL-*` parseado con `atomic_parse()` directamente queda con el campo `text` corrompido (se traga los campos siguientes). Esto diverge además del criterio usado por `knowledge_management.py::_extract_lesson_fields`, que no tiene ninguna lista fija de campos conocidos.

## 3. Evidencia cuantitativa y cualitativa

### 3.1 Mapa de componentes afectados

| Componente | Ruta | Tipo | Problema | Notas |
|---|---|---|---|---|
| `_get_conn` / `_security_pattern` | `src/meridian/server.py:44-49,91-141` | Núcleo de seguridad/auditoría | A | Conexión global de larga duración; `next_sequential_id` deja una transacción abierta antes del `commit()` agregado por el usuario |
| `get_connection` | `src/meridian/db/connection.py:16-22` | Factory de conexión | A | Sin `busy_timeout` en `main`; reutilizada de forma independiente por 14 call sites |
| Tools de escritura/lectura | `src/meridian/tools/knowledge_management.py:358,560,583,999,1040,1069,1136,1218` (8 sitios) | Tools MCP | A | Cada llamada abre y cierra su propia conexión (`try/finally: conn.close()`) |
| Tools de consulta | `src/meridian/tools/knowledge_consumption.py:119,235,317,379,437,478` (6 sitios) | Tools MCP (solo lectura) | A | Mismo patrón, incluso para queries de solo lectura |
| `_BLOCK_HEADER_RE` | `src/meridian/parsers/atomic_parser.py:26` | Parser | B | Exige `{TECH}` = `[A-Z]+`; el ajuste del usuario no compila |
| `_KNOWN_FIELD_NAMES` | `src/meridian/parsers/atomic_parser.py:29-36` | Parser | B | Solo cubre los 6 campos de reglas |
| `_extract_segment` | `src/meridian/utils/id_generator.py:30-36` | Generador de IDs | B | Puede producir `{TECH}` alfanumérico según el `scope_id` |
| `LESSON_TEMPLATE` | `src/meridian/tools/knowledge_templates.py:37-49` | Template canónico | B | Declara 5 campos después de `Qué pasó` que deben reconocerse como límite de campo |
| `_extract_lesson_fields` | `src/meridian/tools/knowledge_management.py:146-166` | Parser alterno (independiente) | B | No usa lista de campos conocidos — cualquier `**Campo:**` es un límite válido |

### 3.2 Patrones repetidos (boilerplate)

**Problema A** — patrón de conexión independiente repetido 14 veces (ejemplo real, `knowledge_management.py:357-374`):

```python
def index_rules_from_markdown(
    filepath: str, default_scope_id: str, mode: str = "atomic"
) -> dict:
    conn = get_connection(get_db_path())
    try:
        result = _new_index_result()
        try:
            ...
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return result
    finally:
        conn.close()
```

- **Número de archivos con este patrón:** 2 (`knowledge_management.py`, `knowledge_consumption.py`)
- **Número de sitios con este patrón:** 14 (8 + 6)
- **Número de variantes del patrón:** 2 — variante "escritura" (abre, hace commit/rollback explícito, cierra) y variante "solo lectura" (abre, lee, cierra sin commit) — ambas abren una conexión nueva por invocación.

**Problema B** — regex actual (rota) vs. original (`atomic_parser.py:26`), verificado en este ambiente:

```python
# main (antes del ajuste):
_BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z]+-\d+", re.MULTILINE)

# working tree del usuario (ajuste actual):
_BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z]+-)?\d+", re.MULTILINE)
```

```
$ uv run python -c "import meridian.parsers.atomic_parser"
  File ".../src/meridian/parsers/atomic_parser.py", line 26, in <module>
    _BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z]+-)?\d+", re.MULTILINE)
re.error: unbalanced parenthesis at position 19
```

- **Archivos con el patrón de ID `RN-{TECH}-NNN`/`LL-{TECH}-NNN`:** todo `knowledge-base/**/*.md` y `lessons/**/*.md`, más los generadores en `utils/id_generator.py` y las plantillas en `tools/knowledge_templates.py`.
- **Escenario que reproduce un indexado en 0 bloques sin error** (hipótesis más plausible, no confirmada por el usuario): un `scope_id` cuyo segmento tras el último guion contiene dígitos — p. ej. un scope custom `global-java17` o `project-app2` — produce, vía `_extract_segment`, un `{TECH}` como `JAVA17` o `APP2`. El regex original `[A-Z]+` no matchea eso, `_BLOCK_HEADER_RE.finditer` no encuentra el header, y `parse()` retorna `([], [])` sin ningún warning ni excepción.

### 3.3 Inconsistencias de configuración

| Configuración | En `main` (antes del ajuste) | Ajuste del usuario (working tree) | ¿Centralizada? |
|---|---|---|---|
| `busy_timeout` | No definido (equivale a 0 — sin espera) | `5000` ms en `db/connection.py:20` | Sí — un solo punto (`get_connection`) |
| Commit de la transacción de `next_sequential_id` antes de correr el tool | No se hacía commit explícito | `c.commit()` agregado en `server.py:98` | Parcial — solo corrige la conexión global de `_security_pattern`; los 14 sitios de `get_connection()` en `tools/` no comparten ningún mecanismo central de commit/retry |
| Campos reconocidos como límite de un campo multilínea | `_FIELD_RE.match(next_line)` sin lista fija (comportamiento original) | `_KNOWN_FIELD_NAMES` con solo 6 campos de **reglas** | No — diverge de `knowledge_management.py::_extract_lesson_fields`, que no usa ninguna lista fija |
| Caracteres permitidos en el segmento `{TECH}` del ID | `[A-Z]+` en el parser (`atomic_parser.py`) | `([A-Z]+-)?\d+` *(regex inválida, no compila)* en el parser | No — `id_generator.py::_extract_segment` no valida ni restringe el segmento que genera; nada impide que un scope produzca un `{TECH}` que el parser luego no reconozca |

### 3.4 Stack tecnológico relevante

```text
Lenguaje:        Python >=3.11 (pyproject.toml)
Framework MCP:   fastmcp >=0.4.0
Persistencia:    sqlite3 (stdlib) — WAL mode, db/connection.py
Vector store:    chromadb >=0.5.0
Embeddings:      sentence-transformers >=3.0.0 (BAAI/bge-small-en-v1.5) + torch >=2.2.0
Dev/test:        pytest >=8.0.0, pytest-asyncio >=0.23.0, ruff >=0.5.0
```

(Versiones extraídas de `pyproject.toml`; son rangos mínimos declarados, no versiones exactas instaladas — no se verificó el lockfile.)

### 3.5 Limitaciones técnicas identificadas

- El módulo `sqlite3` de Python abre una transacción implícita en el primer DML (incluye `UPDATE ... RETURNING`) cuando `isolation_level` no es `None`; `db/connection.py::get_connection` no fija `isolation_level`, por lo que usa el comportamiento por defecto (transacción implícita).
- SQLite en modo WAL permite múltiples lectores concurrentes con un solo escritor, pero **no** permite dos escritores concurrentes: una segunda conexión que intente escribir mientras otra mantiene una transacción de escritura abierta queda bloqueada (o falla de inmediato sin `busy_timeout`).
- `get_connection` fija `check_same_thread=False` en todas las conexiones (`db/connection.py:18`), es decir, el diseño ya asume que una conexión puede cruzar threads — pero no hay ningún lock/mutex alrededor de la conexión global `server.py::conn` para el transporte HTTP/SSE, que por diseño puede atender más de un request a la vez (CLAUDE.md: `meridian serve` imprime un token de sesión, sugiriendo acceso multi-cliente).
- El proceso del servidor MCP (`meridian mcp` / `meridian serve`) y el CLI (`python -m meridian ...`) son procesos de sistema operativo separados que abren conexiones independientes al mismo archivo `$KNOWLEDGE_BASE_PATH/meridian.db` — cualquier mecanismo dentro del proceso del servidor (ej. un pool interno) no puede por sí solo prevenir contención entre el CLI y el servidor; solo mecanismos a nivel de archivo (WAL + `busy_timeout`, o un lock externo) cubren ese caso.
- `legacy_parser.py` usa un formato de bloque estructuralmente distinto (`### ` en vez de `## `) y no comparte `_BLOCK_HEADER_RE` con `atomic_parser.py`, por lo que no sirve como referencia directa de un regex más permisivo ya probado en el repo.
- No se encontró ninguna prueba unitaria para `_extract_segment` con segmentos que contengan dígitos, ni para escritura concurrente de dos conexiones SQLite (revisado `tests/unit/test_connection.py`, `tests/unit/test_id_generator*.py` si existe) — no hay contrato explícito para ninguno de los dos escenarios, solo el comportamiento implícito del código actual.
- El usuario no compartió el traceback/error exacto que vio al indexar antes de su ajuste, ni el `scope_id`/nombre de archivo involucrado — la causa raíz de la sección 2.2/3.2 para el Problema B es la explicación más consistente con el código y el síntoma reportado ("no fue posible indexar"), pero queda como hipótesis, no como hecho confirmado.

## 4. Opciones de solución evaluadas

### 4.1 Problema A — Gestión de conexiones concurrentes

#### Opción A1 – Formalizar el fix puntual (commit temprano + `busy_timeout`)

- **Descripción técnica:** conservar exactamente lo que ya funcionó en el ambiente del usuario — `busy_timeout=5000` en `get_connection` (`db/connection.py`) y un `commit()` explícito inmediatamente después de `next_sequential_id` en `_security_pattern` (`server.py`) — y formalizarlo con una prueba de regresión que abra dos conexiones reales y verifique que la segunda no falla mientras la primera tiene una transacción abierta.
- **Archivos/componentes a modificar:** `src/meridian/db/connection.py`, `src/meridian/server.py`, nuevo test en `tests/unit/test_connection.py` o `tests/integration/`.
- **Cambios esperados en el código:** ~2 líneas de producción (ya presentes en el working tree del usuario) + 1 test nuevo.
- **Ventajas:**
  - Esfuerzo mínimo; ya validado empíricamente por el usuario.
  - No introduce ninguna abstracción nueva ni toca los 14 call sites de `get_connection()`.
- **Desventajas:**
  - No elimina el patrón estructural (14 conexiones independientes por sesión de tools); cualquier tool nuevo que olvide seguir el mismo cuidado puede reproducir una colisión similar en otro punto.
  - `busy_timeout` convierte un fallo duro en una espera de hasta 5 s — bajo alta concurrencia real (no verificada, ver 6.3) podría degradar la latencia percibida en vez de eliminarla.
- **Esfuerzo estimado:** <1 día (el cambio de producción ya existe; falta solo el test de regresión).
- **Riesgos técnicos principales:** falsa sensación de "resuelto" si en el futuro aparece contención en alguno de los otros 13 call sites que no pasan por `_security_pattern`.

#### Opción B1 – Conexión única compartida dentro del proceso del servidor

- **Descripción técnica:** eliminar las llamadas independientes a `get_connection(get_db_path())` dentro de `tools/knowledge_management.py` y `tools/knowledge_consumption.py`, y en su lugar pasar la conexión global de `server.py` (o una inyectada) a cada función de tool como parámetro.
- **Archivos/componentes a modificar:** los 14 call sites de `get_connection()` (`knowledge_management.py`, `knowledge_consumption.py`), sus firmas de función, `server.py` (paso de `conn`), y los tests que instancian estas funciones (probablemente la mayoría de `tests/unit/` y `tests/integration/`, dado que hoy cada test crea su propia conexión vía `get_connection`).
- **Cambios esperados en el código:** eliminación de ~14 pares `get_connection()`/`conn.close()`; adición de un parámetro `conn` en ~14 funciones públicas.
- **Ventajas:**
  - Elimina por completo la colisión *dentro del mismo proceso* (servidor MCP), que es la causa directa reportada por el usuario.
  - Reduce el número de aperturas de conexión por sesión de N (una por tool call) a 1.
- **Desventajas:**
  - No resuelve la colisión *entre procesos* (CLI corriendo junto al servidor) — sigue requiriendo `busy_timeout` como red de seguridad.
  - Cambio de firma en ~14 funciones y en la mayoría de los tests existentes; superficie de regresión amplia.
- **Esfuerzo estimado:** 2-3 días (refactor + actualización de tests).
- **Riesgos técnicos principales:** una transacción larga en la conexión compartida (p. ej. generación de embeddings, que usa `sentence-transformers`/`torch` y puede tardar segundos) bloquearía cualquier otra operación de escritura del mismo proceso durante ese tiempo.

#### Opción C1 – Pool/gestor de conexiones centralizado

- **Descripción técnica:** introducir un módulo (p. ej. `db/pool.py`) con un `contextmanager` o un pool acotado (N conexiones pre-abiertas) del que tanto `server.py` como los 14 call sites de `tools/` obtengan su conexión, en vez de llamar `get_connection(get_db_path())` directamente. Centraliza también el punto donde se podría agregar retry/backoff o métricas de contención más allá de lo que da `busy_timeout` por sí solo.
- **Archivos/componentes a modificar:** nuevo `src/meridian/db/pool.py` (o similar), los 14 call sites, `server.py`, tests de todos los módulos anteriores.
- **Cambios esperados en el código:** nueva abstracción (~50-100 líneas) + refactor de los mismos 14 sitios que la Opción B1, más pruebas específicas del pool.
- **Ventajas:**
  - Único lugar para razonar sobre el ciclo de vida de conexiones, límites de concurrencia y política de reintentos.
  - Punto natural para agregar observabilidad (logging de contención, métricas) que hoy no existe.
- **Desventajas:**
  - Introduce una abstracción que el proyecto no tiene hoy (CLAUDE.md no la menciona); mayor curva de mantenimiento.
  - Mismo alcance de refactor que B1, más el desarrollo y prueba del pool en sí.
- **Esfuerzo estimado:** 3-5 días.
- **Riesgos técnicos principales:** un pool mal dimensionado (muy chico) podría convertirse en un nuevo cuello de botella; mal dimensionado (muy grande) reintroduce el problema original de múltiples escritores.

#### Opción D1 – Solo WAL + `busy_timeout`, sin tocar el patrón de conexiones

- **Descripción técnica:** agregar únicamente `busy_timeout` a `get_connection` (sin el `commit()` temprano en `_security_pattern` ni ningún refactor de los 14 call sites), dejando que toda colisión se resuelva por espera.
- **Archivos/componentes a modificar:** `src/meridian/db/connection.py` únicamente.
- **Cambios esperados en el código:** 1 línea.
- **Ventajas:**
  - El cambio más pequeño posible.
- **Desventajas:**
  - No ataca la causa específica que el usuario reportó (la transacción de `next_sequential_id` quedando abierta durante todo `impl_callable()`, incluida la apertura de una segunda conexión) — según la evidencia de 3.1-3.3, `busy_timeout` solo would haber convertido el fallo inmediato en una espera de hasta 5 s por cada operación de escritura sobre una Global Rule, no lo habría eliminado si `impl_callable()` tarda más que eso.
  - No hay evidencia en este reporte de que esta opción, aislada, sea suficiente — el usuario aplicó ambos cambios juntos.
- **Esfuerzo estimado:** <1 hora.
- **Riesgos técnicos principales:** riesgo de que el síntoma reportado por el usuario reaparezca de forma intermitente (dependiente de cuánto tarde `impl_callable()`).

### Tabla comparativa unificada (Problema A)

| Criterio | Opción A1 | Opción B1 | Opción C1 | Opción D1 |
|---|---|---|---|---|
| Ataca la causa específica reportada por el usuario | ✅ | ✅ | ✅ | Parcial |
| Resuelve colisión entre procesos (CLI vs. servidor) | Parcial (vía timeout) | Parcial (vía timeout) | Parcial (vía timeout) | Parcial (vía timeout) |
| Requiere refactor de los 14 call sites | ❌ | ✅ | ✅ | ❌ |
| Acoplamiento resultante | Bajo | Medio (conexión inyectada) | Medio-alto (nueva abstracción) | Bajo |
| Facilidad de testing | Alta (ya validado) | Media (muchos tests a tocar) | Media (requiere tests del pool) | Alta |
| Escalabilidad a más clientes/tools concurrentes | Baja-media | Media | Alta | Baja |
| Esfuerzo | <1 día | 2-3 días | 3-5 días | <1 hora |
| Riesgo en producción | Bajo | Medio | Medio | Medio-alto (no resuelve el síntoma reportado por sí sola) |

### 4.2 Problema B — Robustez del parser atómico

#### Opción A2 – Ampliar el charset del segmento `{TECH}` + completar `_KNOWN_FIELD_NAMES`

- **Descripción técnica:** cambiar `_BLOCK_HEADER_RE` de `[A-Z]+` a `[A-Z0-9]+` (manteniendo el segmento **obligatorio**, sin volverlo opcional como en el ajuste actual del usuario), y completar `_KNOWN_FIELD_NAMES` con los campos de lecciones (`Proyecto`, `Fecha`, `Severidad del impacto`, `Área afectada`, `Impacto`, `Causa raíz`, `Resolución`, `Originó regla`) además de los de reglas.
- **Archivos/componentes a modificar:** `src/meridian/parsers/atomic_parser.py` (líneas 26, 29-36), `tests/unit/test_atomic_parser.py` (casos nuevos para IDs con dígitos y para bloques `LL-*`).
- **Cambios esperados en el código:** cambio de 1 carácter en el regex + ampliación de un `set` de ~6 a ~14 elementos.
- **Ventajas:**
  - Cambio quirúrgico, de bajo riesgo, no toca el generador de IDs ni el contrato de scopes.
  - Corrige simultáneamente el bug de `_KNOWN_FIELD_NAMES` identificado en 2.2/3.3 que puede corromper el texto de lecciones.
- **Desventajas:**
  - No agrega ninguna señal cuando el archivo tiene 0 matches por otra causa distinta a dígitos en `{TECH}` — el fallo seguiría siendo silencioso ante cualquier otro desajuste de formato.
  - Relaja el contrato de ID (ahora acepta dígitos en `{TECH}`) sin que exista una decisión explícita documentada sobre si eso es deseable.
- **Esfuerzo estimado:** <1 día.
- **Riesgos técnicos principales:** si en el futuro se decide que `{TECH}` nunca debería tener dígitos (Opción C2), este cambio habría que revertirlo.

#### Opción B2 – Validación explícita de "cero bloques encontrados"

- **Descripción técnica:** en `parse()` (o en `index_rules_from_markdown`/`index_lessons_from_markdown`), si el archivo no está vacío pero no se encontró ningún match de `_BLOCK_HEADER_RE`, agregar un warning/error explícito indicando la ruta del archivo y el formato esperado del header, en vez de retornar silenciosamente `indexed: 0`.
- **Archivos/componentes a modificar:** `src/meridian/parsers/atomic_parser.py::parse`, `src/meridian/tools/knowledge_management.py` (manejo del resultado), tests correspondientes.
- **Cambios esperados en el código:** ~10-15 líneas nuevas (una verificación + mensaje).
- **Ventajas:**
  - No cambia ningún contrato de formato existente; es puramente diagnóstico.
  - Complementaria a cualquier otra opción — reduce drásticamente el tiempo de diagnóstico del próximo caso similar (el del usuario tomó una sesión completa de debugging manual).
- **Desventajas:**
  - No corrige la causa raíz por sí sola: si el problema del usuario era efectivamente un `{TECH}` con dígitos, esta opción solo lo hace visible más rápido, no lo resuelve.
- **Esfuerzo estimado:** <1 día.
- **Riesgos técnicos principales:** ninguno significativo; riesgo de falsos positivos si algún flujo legítimamente indexa 0 bloques (p. ej. un archivo recién creado con solo el header de sección, sin bloques aún).

#### Opción C2 – Restringir/normalizar `{TECH}` en el origen (creación de scopes)

- **Descripción técnica:** en vez de ampliar el regex del parser para aceptar lo que `_extract_segment` pueda producir, mantener el contrato original (`{TECH}` = `[A-Z]+`, sin dígitos) y validar ese contrato en el punto donde se crea/registra un `scope_id`, rechazando de forma explícita cualquier scope cuyo segmento final no sea puramente alfabético.
- **Archivos/componentes a modificar:** el tool/flujo de creación de scopes (no localizado en este reporte — no se encontró un tool `create_scope` expuesto en `server.py`; los scopes actuales se insertan solo vía `db/schema.sql` y migraciones), `utils/id_generator.py::_extract_segment` (para fallar temprano en vez de generar un ID que luego no calza), tests nuevos.
- **Cambios esperados en el código:** depende de si existe o no un flujo de creación de scopes en tiempo de ejecución (no confirmado en este reporte — ver limitación en 3.5).
- **Ventajas:**
  - Es la única opción que mantiene el contrato de ID original intacto, moviendo la validación "aguas arriba" (en el momento de crear el scope) en vez de "aguas abajo" (al indexar meses después).
- **Desventajas:**
  - Mayor esfuerzo y alcance incierto, ya que depende de un flujo de creación de scopes que no fue localizado explícitamente en el código (los 19 scopes actuales son datos semilla en `schema.sql`, no hay una función API para crear scopes en runtime confirmada en este reporte).
  - No ayuda si el usuario ya tiene scopes existentes con `{TECH}` alfanumérico — requeriría migración de datos.
- **Esfuerzo estimado:** No disponible con precisión — depende de un flujo no confirmado; estimación preliminar 2-4 días si el flujo existe, mayor si hay que construirlo.
- **Riesgos técnicos principales:** alcance subestimado si aparecen más puntos de creación de scope de los identificados aquí.

#### Opción D2 – Fallback automático a `legacy_parse()` cuando el header atómico no matchea

- **Descripción técnica:** si `_BLOCK_HEADER_RE.finditer()` no encuentra nada en un archivo con contenido, delegar automáticamente a `legacy_parse()` (que ya genera `pending_proposals` en vez de filas directas), en lugar de reportar `indexed: 0`.
- **Archivos/componentes a modificar:** `src/meridian/tools/knowledge_management.py` (las funciones `index_rules_from_markdown`/`index_lessons_from_markdown`), tests de integración del flujo de indexado.
- **Cambios esperados en el código:** ~15-20 líneas (detección + delegación).
- **Ventajas:**
  - Coincide con el invariante ya documentado ("legacy content only ever becomes pending_proposals") — reutiliza un camino de datos que ya existe y ya es seguro (no escribe directo a `rules`/`lessons`).
  - Nunca deja un archivo "sin ningún resultado": siempre produce filas o propuestas.
- **Desventajas:**
  - Puede enmascarar errores reales de formato: un archivo que **sí** pretendía ser atómico pero tiene un typo quedaría silenciosamente reinterpretado como legacy, generando `pending_proposals` en vez de una señal clara de "arregla el header".
  - Mayor complejidad de flujo (dos parsers coordinados en el mismo punto de entrada).
- **Esfuerzo estimado:** 1-2 días.
- **Riesgos técnicos principales:** comportamiento sorprendente para el usuario si un archivo atómico mal formado termina como propuestas legacy en vez de fallar de forma explícita.

### Tabla comparativa unificada (Problema B)

| Criterio | Opción A2 | Opción B2 | Opción C2 | Opción D2 |
|---|---|---|---|---|
| Preserva el contrato de ID original (`{TECH}` sin dígitos) | ❌ (lo relaja) | ✅ (no lo toca) | ✅ (lo refuerza) | ✅ (no lo toca) |
| Corrige el bug de `_KNOWN_FIELD_NAMES` en lecciones | ✅ | ❌ (no aplica) | ❌ (no aplica) | ❌ (no aplica) |
| Convierte el fallo silencioso en visible | ❌ | ✅ | Parcial (previene, no diagnostica) | Parcial (produce propuestas en vez de error) |
| Requiere localizar/tocar un flujo no confirmado (creación de scopes) | ❌ | ❌ | ✅ | ❌ |
| Facilidad de testing | Alta | Alta | Media (depende del flujo real) | Media |
| Retrocompatibilidad con datos ya indexados | ✅ | ✅ | Requiere migración si ya hay scopes alfanuméricos | ✅ |
| Esfuerzo | <1 día | <1 día | 2-4 días (estimado, incierto) | 1-2 días |
| Riesgo en producción | Bajo | Bajo | Medio (alcance incierto) | Medio (comportamiento sorpresa) |

## 5. Restricciones de diseño inamovibles

- Markdown sigue siendo la única fuente de verdad (CLAUDE.md); ninguna solución al Problema B puede inferir o rellenar contenido de conocimiento que no provenga del `.md` — un fallo de parseo debe traducirse en warning/propuesta, nunca en datos inventados.
- El formato canónico de ID (`RN-{TECH}-NNN` / `LL-{TECH}-NNN`) y las etiquetas de campo en español son invariantes documentados; cambiar una etiqueta requiere tocar `atomic_parser.py`, `_build_*_atomic_block` (`knowledge_management.py`), `_extract_lesson_fields` y `knowledge_templates.py` en conjunto (CLAUDE.md).
- El contenido legacy solo puede convertirse en `pending_proposals`, nunca escribirse directo a `rules`/`lessons` — cualquier opción tipo "fallback a legacy" (D2) debe respetar ese camino existente, no crear uno nuevo que escriba directo.
- ADR-005 (ruta de lectura indexada) ya desacopló las lecturas de `detail="full"` de los offsets de archivo; ninguna solución al Problema B debe reintroducir esa dependencia en el read path.
- No hay un entorno de carga/multi-cliente real documentado para validar concurrencia (CLAUDE.md solo describe `meridian serve` como transporte HTTP/SSE con token de sesión) — cualquier afirmación sobre el comportamiento bajo concurrencia real de producción queda fuera del alcance verificable de este reporte (ver 6.3).
- El usuario ya tiene una copia de trabajo local modificada como workaround (`git status`: `db/connection.py`, `parsers/atomic_parser.py`, `server.py`); la decisión debe partir de ese estado (parte ya es reutilizable, parte debe descartarse), no de una reescritura desde cero.

## 6. Anexo técnico

### 6.1 Árbol de archivos potencialmente afectados (unión de todas las opciones)

**Problema A**

```text
src/meridian/db/connection.py                 [MODIFICAR — A1, B1, C1, D1]
src/meridian/server.py                        [MODIFICAR — A1, B1, C1]
src/meridian/tools/knowledge_management.py    [MODIFICAR — B1, C1 (8 call sites)]
src/meridian/tools/knowledge_consumption.py   [MODIFICAR — B1, C1 (6 call sites)]
src/meridian/db/pool.py                       [NUEVO — solo C1]
tests/unit/test_connection.py                 [MODIFICAR — A1, B1, C1, D1]
```

**Problema B**

```text
src/meridian/parsers/atomic_parser.py         [MODIFICAR — A2, B2]
src/meridian/tools/knowledge_management.py    [MODIFICAR — B2, D2]
src/meridian/utils/id_generator.py            [MODIFICAR — solo C2]
tests/unit/test_atomic_parser.py              [MODIFICAR — A2, B2, D2]
```

### 6.2 Fragmentos representativos (sin decidir cuál)

Cómo se ve hoy (`main`, funcional pero estricto):

```python
_BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z]+-\d+", re.MULTILINE)
```

Alternativas posibles documentadas en la sección 4.2 (ninguna elegida aquí):

```python
# Opción A2 — admite dígitos en {TECH}, segmento sigue siendo obligatorio
_BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z0-9]+-\d+", re.MULTILINE)

# Ajuste actual del usuario — NO compila (paréntesis sin abrir), incluido solo como referencia del intento:
_BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z]+-)?\d+", re.MULTILINE)
```

### 6.3 Resultados de análisis automático

No disponible. No hay herramienta de complejidad ciclomática ni de profiling de concurrencia instalada en el repositorio (no aparece en `pyproject.toml`), y no se compartieron métricas ni logs del ambiente de prueba del usuario donde ocurrieron los dos incidentes. Un análisis dinámico posterior podría instrumentar `db/connection.py` con dos conexiones reales bajo `pytest` (hilos o subprocesos) para medir la tasa de `SQLITE_BUSY` con y sin `busy_timeout`, y correr `index_rules_from_markdown` contra un archivo con un `scope_id` alfanumérico sintético para confirmar o descartar la hipótesis de la sección 3.2.

## 7. Instrucciones para el arquitecto (lo que se espera de él)

1. Elegir **UNA** opción para el Problema A (4.1) y **UNA** opción para el Problema B (4.2) — pueden decidirse de forma independiente o como paquete único, basándose en criterios de bajo acoplamiento, mantenibilidad a 5 años y riesgo.
2. Justificar cada decisión citando evidencia de este reporte (secciones 2, 3 y 4).
3. Describir los trade-offs frente a las alternativas descartadas, para cada uno de los dos problemas.
4. Generar un diagrama Mermaid de la arquitectura objetivo (puede ser uno solo que cubra tanto el ciclo de vida de conexiones como el pipeline de indexado/parseo).
5. Autoevaluar los tres riesgos más probables del diseño resultante y proponer mitigaciones.
