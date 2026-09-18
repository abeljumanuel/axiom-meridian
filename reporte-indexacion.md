# Reporte Técnico: Problemas de Indexación y Migración en Meridian

**Fecha:** 2026-06-12  
**Rama:** main  
**Commit:** a3a2f47  
**Autor del reporte:** Ingeniero de Software  
**Destinatario:** Arquitecto de Software / Tech Lead  

---

## 1. Resumen Ejecutivo

El sistema de migración de conocimiento (`migrate rules`) presenta fallas críticas en la identificación del alcance (scope) y en la compatibilidad de formatos. Durante la migración de 30 reglas de Clean Code, se detectó que:

1. **Todas las reglas fueron asignadas erróneamente al scope `global-go`** en lugar de `global`, debido a un keyword matching naive que interpreta "código" como el lenguaje Go.

2. **Incompatibilidad entre formatos**: El sistema no detecta automáticamente si un archivo está en formato atómico (destino) o legacy (origen), forzando al usuario a transformar manualmente el contenido.

3. **Falta de validación de scope**: El parámetro `--scope` es ignorado cuando el sistema infiere un scope diferente mediante keywords.

4. **Campos problemáticos**: El campo `Category` contiene la subcadena "go" (categ**ory**), activando falsos positivos en la inferencia.

Este reporte documenta 4 opciones de solución con sus respectivos esfuerzos, riesgos y trade-offs, para que el arquitecto tome la decisión final.

---

## 2. Contexto y Alcance

### 2.1 Stack Tecnológico

| Componente | Versión | Ubicación |
|------------|---------|-----------|
| Python | 3.11+ | pyproject.toml |
| SQLite | 3.x | Sistema |
| ChromaDB | 0.5.0+ | pyproject.toml |
| fastmcp | 0.4.0+ | pyproject.toml |

### 2.2 Componentes Afectados

| Archivo | Líneas | Función |
|---------|--------|---------|
| `src/meridian/tools/knowledge_management.py` | 1,347 | Lógica de migración e inferencia de scope (líneas 981-1004) |
| `src/meridian/parsers/legacy_parser.py` | 111 | Parser para formato legacy (`### ` headings) |
| `src/meridian/parsers/atomic_parser.py` | 151 | Parser para formato atómico (`## RN-XXX-NNN`) |
| `src/meridian/__main__.py` | 158 | CLI - comando `migrate` |

### 2.3 Magnitud del Problema

- **Archivos de parser:** 2 implementaciones separadas (legacy + atómico)
- **Lógica de inferencia:** 8 keywords hardcodeadas (líneas 987-1002)
- **Campos esperados por legacy parser:** `Category`, `Severity` (ambos contienen subcadenas problemáticas)
- **Impacto:** Cualquier regla con palabras como "código", "cargo", "embargo", "bypass", "undergo" será mal clasificada

---

## 3. Análisis Detallado del Problema

### 3.1 Lógica de Inferencia Defectuosa

**Ubicación:** `src/meridian/tools/knowledge_management.py:987-1002`

```python
# Scope inference (basic keyword matching)
if "quarkus" in raw_lower:
    inferred_scope = "global-quarkus"
elif "java" in raw_lower:
    inferred_scope = "global-java"
# ... más keywords ...
elif "go" in raw_lower:  # ← PROBLEMA: "código" contiene "go"
    inferred_scope = "global-go"
```

**Problema:** El matching es substring, no word-boundary. Cualquier palabra que contenga "go" activa el scope `global-go`.

**Evidencia de palabras problemáticas en español:**
- `código` → contiene `go`
- `cargo` → contiene `go`
- `embargo` → contiene `go`
- `bypass` → contiene `go`
- `undergo` → contiene `go`

### 3.2 Incompatibilidad de Formatos

**Formato Legacy** (esperado por `migrate rules`):
```markdown
## Naming

### Use intention-revealing names
- **Category**: naming
- **Severity**: critical
- **Rule**: Usa nombres...
```

**Formato Atómico** (archivos en `knowledge-base/global/`):
```markdown
## RN-GLOBAL-001
**Scope:** global
**Categoría:** naming
**Severidad:** critical
**Regla:** Usa nombres...
```

**Problema:** El comando `migrate rules` **solo** usa `legacy_parser.py`, que busca headers `### `. Si el archivo está en formato atómico, retorna 0 bloques y no reporta error.

### 3.3 Ignorancia del Parámetro `--scope`

**Ubicación:** `src/meridian/tools/knowledge_management.py:983-1004`

El parámetro `default_scope_id` pasado vía CLI es usado solo como fallback cuando ningún keyword coincide. Si hay match, se sobrescribe sin advertencia al usuario.

### 3.4 Variantes del Patrón Detectadas

| Variante | Comportamiento | Archivo Afectado |
|----------|---------------|------------------|
| Formato atómico con código RN-XXX-NNN | Parser legacy retorna 0 bloques | `clean-code.md` original |
| Campo "Categoría" en español | No mapeado a metadata | Todos los archivos ES |
| Palabras con subcadena "go" | Scope erróneo `global-go` | Cualquier regla en español |
| Scope diferente al solicitado | Silenciosamente ignorado | Todos |

---

## 4. Opciones de Solución

### 4.1 Opción A: Word-Boundary Matching (Fix Inmediato)

**Descripción:** Modificar la lógica de inferencia para usar word boundaries (regex `\b`) en lugar de substring matching.

**Cambios requeridos:**
- Archivo: `src/meridian/tools/knowledge_management.py`
- Líneas: 987-1002
- Esfuerzo: ~30 minutos
- Riesgo: Bajo

**Implementación:**
```python
import re
# ...
WORD_PATTERNS = {
    r'\bquarkus\b': 'global-quarkus',
    r'\bjava\b': 'global-java',
    r'\bgo\b': 'global-go',  # Ahora "código" NO coincide
    # ...
}

for pattern, scope in WORD_PATTERNS.items():
    if re.search(pattern, raw_lower):
        inferred_scope = scope
        break
```

**Ventajas:**
- Fix mínimo y rápido
- Resuelve falsos positivos inmediatamente
- No cambia la interfaz CLI

**Desventajas:**
- No resuelve la incompatibilidad de formatos
- Mantiene la lógica de inferencia opaca al usuario
- No valida el scope explícito vs inferido

---

### 4.2 Opción B: Validación de Scope con Advertencia

**Descripción:** Comparar el scope inferido con el `default_scope_id` proporcionado. Si difieren, advertir al usuario y permitir elegir.

**Cambios requeridos:**
- Archivo: `src/meridian/tools/knowledge_management.py`
- Líneas: 981-1067 (función `convert_to_atomic_format`)
- Esfuerzo: ~2 horas
- Nuevo comportamiento: Validación + prompt interactivo

**Implementación:**
```python
if inferred_scope != default_scope_id:
    # Guardar ambos scopes en metadata
    metadata["scope_inferred"] = inferred_scope
    metadata["scope_explicit"] = default_scope_id
    metadata["scope_conflict"] = True
```

**Ventajas:**
- Transparencia para el usuario
- No rompe flujos existentes (non-breaking)
- Permite auditoría de decisiones

**Desventajas:**
- Requiere modificar schema de `pending_proposals`
- Mayor complejidad en el CLI
- No resuelve incompatibilidad de formatos

---

### 4.3 Opción C: Auto-Detección de Formato + Import Directo

**Descripción:** Implementar detección automática del formato (legacy vs atómico) y crear comando `import` para archivos ya en formato destino.

**Cambios requeridos:**
1. Nueva función: `detect_format(filepath)` en `parsers/__init__.py`
2. Modificar `convert_to_atomic_format` para usar el parser correcto
3. Nuevo comando CLI: `python -m meridian import rules <file> --scope <id>`
4. Archivos modificados: `__main__.py`, `knowledge_management.py`, parsers

**Esfuerzo:** ~1 día
**Riesgo:** Medio (cambia flujo de migración)

**Implementación de detección:**
```python
def detect_format(filepath: str) -> str:
    with open(filepath) as f:
        content = f.read()
    # Buscar patrón atómico
    if re.search(r'^## (RN|LL)-[A-Z]+-\d+', content, re.M):
        return 'atomic'
    # Buscar patrón legacy
    if re.search(r'^### .+', content, re.M):
        return 'legacy'
    return 'unknown'
```

**Ventajas:**
- Solución completa al problema de formatos
- UX mejorada (no requiere transformación manual)
- Permite importar archivos ya en formato destino

**Desventajas:**
- Mayor esfuerzo de implementación
- Requiere testing de ambos parsers
- Cambio significativo en la interfaz

---

### 4.4 Opción D: Remoción de Inferencia + Scope Explícito Obligatorio

**Descripción:** Eliminar completamente la lógica de inferencia por keywords y hacer obligatorio el parámetro `--scope`. El usuario siempre especifica el scope deseado.

**Cambios requeridos:**
- Eliminar líneas 987-1004 de `knowledge_management.py`
- Hacer `--scope` requerido en CLI (línea 62)
- Actualizar documentación

**Esfuerzo:** ~1 hora
**Riesgo:** Medio-Alto (breaking change)

**Ventajas:**
- Elimina toda fuente de falsos positivos
- Comportamiento determinista y predecible
- Más simple de mantener

**Desventajas:**
- Breaking change: rompe scripts existentes
- Menos "inteligente" (el usuario debe saber el scope)
- Requiere actualización de documentación y ejemplos

---

## 5. Restricciones y Limitaciones

### 5.1 Técnicas

1. **Parser legacy fijo**: El formato `### ` + bullets es el estándar de entrada esperado por la herramienta. Cambiarlo afectaría la compatibilidad con archivos existentes.

2. **ChromaDB embebido**: El vector store no permite validación de scopes en tiempo de indexación. La validación debe hacerse en capa SQLite.

3. **MCP Server**: Si se modifica la interfaz de `convert_to_atomic_format`, debe mantenerse compatibilidad con el protocolo MCP.

### 5.2 De Negocio

1. **Backwards compatibility**: Los usuarios actuales pueden tener scripts que dependen del comportamiento actual (inferencia automática).

2. **Multi-idioma**: El sistema debe soportar reglas en español e inglés, lo que complica el keyword matching.

3. **Performance**: La detección de formato no debe agregar latencia significativa (>100ms) al procesar archivos grandes (>1000 líneas).

---

## 6. Anexos

### 6.1 Fragmentos de Código Problemáticos

**Inferencia naive (knowledge_management.py:987-1000):**
```python
if "quarkus" in raw_lower:
    inferred_scope = "global-quarkus"
elif "java" in raw_lower:
    inferred_scope = "global-java"
elif "nestjs" in raw_lower:
    inferred_scope = "global-nestjs"
elif "spring-boot" in raw_lower:
    inferred_scope = "global-spring-boot"
elif "go-fiber" in raw_lower:
    inferred_scope = "global-go-fiber"
elif "go-gin" in raw_lower:
    inferred_scope = "global-go-gin"
elif "go" in raw_lower:  # ← Falso positivo con "código"
    inferred_scope = "global-go"
```

### 6.2 Evidencia de Falsos Positivos

**Palabras en español que activan `global-go`:**
```text
código    → contiene "go" en posición 3
cargo     → contiene "go" en posición 3
embargo   → contiene "go" en posición 4
undergo   → contiene "go" en posición 5 (inglés)
bypass    → contiene "go" en ninguna posición (no, solo "go")
```

### 6.3 Tabla Comparativa de Opciones

| Criterio | Opción A (Word-Boundary) | Opción B (Validación) | Opción C (Auto-Detect) | Opción D (Remover Inferencia) |
|----------|-------------------------|----------------------|------------------------|------------------------------|
| **Esfuerzo** | 30 min | 2 horas | 1 día | 1 hora |
| **Riesgo en producción** | Bajo | Medio | Medio | Alto (breaking) |
| **Resuelve falsos positivos** | ✅ Sí | ⚠️ Parcial | ✅ Sí | ✅ Sí |
| **Resuelve formatos** | ❌ No | ❌ No | ✅ Sí | ❌ No |
| **Transparencia UX** | ❌ Baja | ✅ Alta | ✅ Alta | ✅ Alta |
| **Backwards compatible** | ✅ Sí | ✅ Sí | ✅ Sí | ❌ No |
| **Facilidad de testing** | ✅ Alta | ⚠️ Media | ⚠️ Media | ✅ Alta |
| **Mantenibilidad** | ⚠️ Media | ⚠️ Media | ✅ Alta | ✅ Alta |

---

## 7. Instrucciones para el Arquitecto

Este reporte presenta 4 opciones viables, cada una con trade-offs distintos:

- **Si la prioridad es estabilidad inmediata:** Opción A (word-boundary matching) o D (remover inferencia, aceptando el breaking change).

- **Si la prioridad es UX y prevención futura:** Opción C (auto-detección + import directo) ofrece la solución más completa.

- **Si se busca un balance:** Opción B (validación con advertencia) mejora la transparencia sin romper compatibilidad.

**Recomendación para decisión:**
1. Revisar la Tabla Comparativa (sección 6.3)
2. Considerar el roadmap de producto: ¿Se planea soportar más lenguajes? ¿Más formatos?
3. Evaluar el impacto del breaking change en Opción D vs el beneficio a largo plazo

**Siguiente paso:** Seleccionar una opción y proceder a redactar el ADR (Architecture Decision Record) correspondiente.

---

## 8. Referencias

1. `src/meridian/tools/knowledge_management.py` - Lógica de migración
2. `src/meridian/parsers/legacy_parser.py` - Parser formato legacy
3. `src/meridian/parsers/atomic_parser.py` - Parser formato atómico
4. `src/meridian/__main__.py` - Interfaz CLI
5. Ejemplo de archivo problemático: `clean-code.md` (formato atómico, 30 reglas)

---

*Fin del Reporte Técnico*
