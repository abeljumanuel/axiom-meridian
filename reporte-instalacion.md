# Reporte Técnico: Configuración de Meridian MCP para Multi-Cliente

**Fecha:** 2026-06-12  
**Rama:** main  
**Commit:** a3a2f47  
**Proyecto:** axiom-meridian  
**Autor:** Ingeniero de Software  
**Destinatario:** Arquitecto de Software / Tech Lead  

---

## 1. Resumen Ejecutivo

El sistema Meridian presenta **tres problemas críticos** que impiden su despliegue efectivo como servidor MCP (Model Context Protocol) en entornos de desarrollo:

1. **Editable Install Fallido**: El paquete `axiom-meridian` instalado con `uv pip install -e .` no expone el módulo `meridian` al `sys.path`, forzando el uso de workarounds con `PYTHONPATH=src`.

2. **Incompatibilidad Hatchling-uv**: Los archivos `.pth` generados por Hatchling para editable installs no son procesados correctamente por el intérprete Python en entornos uv, dejando `src/` fuera del path de importación.

3. **Configuración MCP Fragmentada**: Cada cliente (Claude Code, VSCode, OpenCode, Kimi CLI) requiere configuración específica con rutas absolutas al venv, creando fragilidad en el despliegue.

Este reporte documenta **4 opciones de solución** para habilitar el servicio de forma natural y disponibilizar el MCP en múltiples clientes sin inconvenientes.

---

## 2. Contexto y Alcance

### 2.1 Stack Tecnológico

| Componente | Versión | Ubicación | Rol |
|------------|---------|-----------|-----|
| Python | 3.11.14 | pyproject.toml | Runtime |
| Hatchling | 1.x | `[build-system]` | Build backend |
| uv | 0.6.x+ | gestor de paquetes | Package manager |
| fastmcp | 0.4.0+ | pyproject.toml | MCP framework |
| ChromaDB | 0.5.0+ | pyproject.toml | Vector store |
| sentence-transformers | 3.0.0+ | pyproject.toml | Embeddings |

### 2.2 Componentes Afectados

| Archivo | Líneas | Función |
|---------|--------|---------|
| `pyproject.toml` | 56 | Configuración de build, entry points, dependencias |
| `src/meridian/__init__.py` | 3 | Package init (vacío excepto versión) |
| `src/meridian/__main__.py` | 158 | CLI entry point (`python -m meridian`) |
| `src/meridian/server.py` | 586 | FastMCP server, tool registration |
| `scripts/install.sh` | 479 | Instalación y configuración MCP clients |
| `opencode.json` | 17 | Configuración OpenCode MCP |
| `CLAUDE.md` | 70 | Documentación para Claude Code |

### 2.3 Magnitud del Problema

- **Clientes MCP objetivo:** 4 (Claude Code, VSCode, OpenCode, Kimi CLI)
- **Workarounds requeridos actualmente:** 1 (`PYTHONPATH=src`)
- **Archivos .pth problemáticos:** 2 (uno con espacio en nombre: `_editable_impl_axiom_meridian 2.pth`)
- **Entry points disponibles:** 1 (`python -m meridian`)
- **Usuarios impactados:** Todos los desarrolladores del equipo

---

## 3. Análisis Detallado

### 3.1 Estructura de Paquete y Build

**Layout actual (src-layout):**
```
axiom-meridian/
├── src/
│   └── meridian/           ← Código fuente
│       ├── __init__.py
│       ├── __main__.py
│       └── ...
├── pyproject.toml
└── .venv/
```

**Configuración en `pyproject.toml`:**
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/meridian"]
```

### 3.2 Falla del Editable Install

**Ubicación:** `.venv/lib/python3.11/site-packages/*.pth`

**Archivos generados:**
```bash
-rw-r--r--@ 45 Jun 12 00:54 _editable_impl_axiom_meridian.pth
-rw-------  45 Jun 11 23:36 _editable_impl_axiom_meridian 2.pth  ← Con espacio
```

**Contenido de los archivos .pth:**
```
/Users/developer/Documents/axiom-meridian/src
```

**Problema:** Aunque los archivos .pth existen y contienen la ruta correcta, **no están siendo procesados** por el intérprete Python al iniciar. Verificación:

```python
>>> import sys
>>> '/Users/developer/Documents/axiom-meridian/src' in sys.path
False  # ← El path no está presente
```

### 3.3 Incompatibilidad Hatchling + uv

**Causa raíz:** Hatchling genera archivos `.pth` con un formato específico para editable installs que depende de un hook de importación. En entornos creados con `uv`, este hook no se activa correctamente debido a diferencias en cómo uv gestiona los site-packages y el orden de inicialización.

**Evidencia técnica:**
- El archivo `_editable_impl_axiom_meridian.pth` contiene la ruta correcta
- `site.addsitedir()` no procesa el path adicional
- El duplicado con espacio (`... 2.pth`) sugiere conflictos en la instalación

### 3.4 Variantes del Problema Detectadas

| Variante | Comportamiento | Contexto |
|----------|---------------|----------|
| `python -m meridian` | `No module named meridian` | Sin PYTHONPATH |
| `PYTHONPATH=src python -m meridian` | ✅ Funciona | Workaround manual |
| `uv run python -m meridian` | ❌ Falla | uv no expone el editable correctamente |
| MCP clients | ❌ Fallan silenciosamente | No tienen PYTHONPATH configurado |

---

## 4. Opciones de Solución

### 4.1 Opción A: Reinstalación con Modo Compatibilidad

**Descripción:** Reinstalar el paquete usando el modo de compatibilidad de Hatchling que genera symlinks en lugar de archivos .pth complejos.

**Comandos:**
```bash
# Desinstalar primero
uv pip uninstall axiom-meridian

# Reinstalar en modo compatibilidad
uv pip install -e . --config-settings editable_mode=compat
```

**Cambios en `pyproject.toml` (opcional):**
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/meridian"]

[tool.hatch.build.hooks.vcs]
version-file = "src/meridian/_version.py"
```

**Esfuerzo:** 10 minutos  
**Riesgo:** Bajo  
**Breaking:** No

**Ventajas:**
- Solución rápida y no invasiva
- No requiere cambios en el código fuente
- Compatible con todos los clientes MCP

**Desventajas:**
- Requiere reinstalación en cada entorno
- No soluciona el problema de raíz (incompatibilidad uv/Hatchling)
- El modo `compat` puede ser más lento en Windows

---

### 4.2 Opción B: Script Wrapper con PYTHONPATH

**Descripción:** Crear un script shell/batch que configure `PYTHONPATH` antes de ejecutar el servidor MCP.

**Archivo nuevo:** `scripts/meridian-mcp.sh`
```bash
#!/bin/bash
# Wrapper para Meridian MCP server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/.venv"

export PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH"
export KNOWLEDGE_BASE_PATH="${KNOWLEDGE_BASE_PATH:-$HOME/Library/Application Support/meridian}"
export MERIDIAN_ACCESS_LEVEL="${MERIDIAN_ACCESS_LEVEL:-write}"

exec "$VENV_DIR/bin/python" -m meridian mcp "$@"
```

**Actualización de configuraciones MCP:**
- Claude Code: `claude mcp add meridian ./scripts/meridian-mcp.sh`
- OpenCode: Actualizar `command` en `opencode.json`
- VSCode: Actualizar `mcp.json` para usar el script

**Esfuerzo:** 30 minutos  
**Riesgo:** Medio  
**Breaking:** No

**Ventajas:**
- Funciona inmediatamente sin reinstalación
- Centraliza la configuración de entorno
- Fácil de debuggear (el script puede loggear)

**Desventajas:**
- Añade una capa de indirección
- Requiere mantenimiento del script wrapper
- En Windows requiere versión `.bat` adicional

---

### 4.3 Opción C: Entry Point Script Nativo

**Descripción:** Configurar Hatchling para generar un entry point nativo en lugar de depender de `python -m meridian`.

**Cambios en `pyproject.toml`:**
```toml
[project.scripts]
meridian = "meridian.__main__:main"
meridian-mcp = "meridian.server:run_stdio"

[project.entry-points."meridian.mcp"]
main = "meridian.server:run_stdio"
```

**Script wrapper actualizado (`scripts/meridian-mcp.sh`):**
```bash
#!/bin/bash
# Usa el entry point nativo en lugar de python -m
exec "$VENV_DIR/bin/meridian-mcp" "$@"
```

**Reinstalación requerida:**
```bash
uv pip install -e .
```

**Esfuerzo:** 1 hora  
**Riesgo:** Medio  
**Breaking:** No (añade funcionalidad)

**Ventajas:**
- Entry point nativo más robusto que `python -m`
- Mejor integración con shell/CLI
- Permite múltiples comandos (`meridian`, `meridian-mcp`)
- El editable install funciona porque el script se instala en `bin/`

**Desventajas:**
- Requiere modificar `pyproject.toml`
- Necesita reinstalación del paquete
- Los entry points pueden no propagar señales correctamente en MCP

---

### 4.4 Opción D: Migración a PDME (PEP 660) Puro

**Descripción:** Eliminar Hatchling y usar una configuración más simple con setuptools o flit que implemente PEP 660 de forma nativa.

**Cambios en `pyproject.toml`:**
```toml
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-dir]
"" = "src"
```

**Restructuración opcional (flat-layout):**
```
axiom-meridian/
├── meridian/              ← Mover desde src/meridian/
│   ├── __init__.py
│   └── ...
└── pyproject.toml
```

**Esfuerzo:** 2-3 horas  
**Riesgo:** Alto  
**Breaking:** Potencial (cambio de build backend)

**Ventajas:**
- Elimina la incompatibilidad Hatchling-uv
- setuptools tiene mejor soporte para editable installs
- Más predecible en diferentes entornos

**Desventajas:**
- Cambio significativo de build backend
- Puede requerir ajustes en CI/CD
- Riesgo de romper funcionalidades específicas de Hatchling
- Necesita testing exhaustivo

---

## 5. Restricciones y Limitaciones

### 5.1 Técnicas

1. **uv como gestor de paquetes obligatorio:** El equipo usa uv para consistencia con el resto del stack. Soluciones que requieran migrar a pip/poetry no son viables.

2. **MCP sobre stdio:** Todos los clientes MCP usan transporte stdio, lo que requiere que el proceso permanezca vivo y maneje señales correctamente.

3. **Paths absolutos en config:** Los archivos de configuración MCP (`~/.claude.json`, `~/.config/opencode/opencode.json`) requieren paths absolutos al ejecutable, lo que dificulta la portabilidad entre máquinas.

4. **Hatchling features usadas:** El proyecto usa `[tool.hatch.build.targets.wheel]` que puede tener funcionalidades específicas de Hatchling (a verificar).

### 5.2 De Negocio

1. **Multiplataforma:** La solución debe funcionar en macOS (desarrollo) y Linux (CI/producción).

2. **Onboarding rápido:** Nuevos desarrolladores deben poder levantar el entorno en < 5 minutos.

3. **Compatibilidad MCP:** Debe funcionar con Claude Code, VSCode, OpenCode y Kimi CLI sin configuración adicional por cliente.

4. **Sin breaking changes:** Las soluciones no deben romper el flujo de trabajo actual de los desarrolladores que ya usan el workaround `PYTHONPATH=src`.

---

## 6. Anexos

### 6.1 Evidencia del Problema

**Verificación de sys.path:**
```python
>>> import sys
>>> [p for p in sys.path if 'meridian' in p.lower()]
['/Users/developer/Documents/axiom-meridian/.venv/lib/python3.11/site-packages']
# Nota: src/ NO está en el path
```

**Contenido de archivos .pth:**
```bash
$ cat .venv/lib/python3.11/site-packages/_editable_impl_axiom_meridian.pth
/Users/developer/Documents/axiom-meridian/src
```

**Falla del import:**
```bash
$ .venv/bin/python -m meridian version
.venv/bin/python: No module named meridian
```

### 6.2 Configuraciones MCP Actuales

**OpenCode (`opencode.json`):**
```json
{
  "mcp": {
    "meridian": {
      "type": "local",
      "command": ["/Users/developer/Documents/axiom-meridian/.venv/bin/python", "-m", "meridian", "mcp"],
      "environment": {
        "MERIDIAN_ACCESS_LEVEL": "write"
      }
    }
  }
}
```

**Claude Code (equivalente):**
```bash
claude mcp add -s user -e MERIDIAN_ACCESS_LEVEL=write -- meridian \
  /Users/developer/Documents/axiom-meridian/.venv/bin/python \
  -m meridian mcp
```

### 6.3 Tabla Comparativa de Opciones

| Criterio | Opción A (Reinstalar compat) | Opción B (Wrapper Script) | Opción C (Entry Point) | Opción D (Migrar setuptools) |
|----------|------------------------------|---------------------------|------------------------|------------------------------|
| **Esfuerzo** | 10 min | 30 min | 1 hora | 2-3 horas |
| **Riesgo** | Bajo | Medio | Medio | Alto |
| **Breaking** | No | No | No | Potencial |
| **Reinstalación req.** | ✅ Sí | ❌ No | ✅ Sí | ✅ Sí |
| **Cambios código** | ❌ No | ⚠️ Nuevo archivo | ⚠️ pyproject.toml | ✅ Build backend |
| **Portabilidad** | ⚠️ Media | ✅ Alta | ✅ Alta | ✅ Alta |
| **Windows support** | ⚠️ Lento | ⚠️ Script extra | ✅ Nativo | ✅ Nativo |
| **Mantenimiento** | ⚠️ Bajo | ⚠️ Medio | ✅ Bajo | ✅ Bajo |
| **Long-term viability** | ⚠️ Temporal | ✅ Permanente | ✅ Permanente | ✅ Permanente |

---

## 7. Instrucciones para el Arquitecto

Este reporte presenta 4 opciones viables, cada una con diferentes trade-offs:

### Recomendación por Contexto

- **Si necesitas solución inmediata (hoy):** Opción A (reinstalar con `editable_mode=compat`) o Opción B (script wrapper).

- **Si buscas solución permanente y robusta:** Opción C (entry point nativo) ofrece el mejor balance de esfuerzo/valor.

- **Si el problema persiste o escala:** Opción D (migrar a setuptools) elimina la dependencia problemática, pero requiere testing exhaustivo.

### Mi Recomendación Técnica (fuera del reporte)

**Opción C (Entry Point Nativo)** es la más apropiada porque:
1. Es una solución estándar de Python (PEP 518/621)
2. Elimina la dependencia de PYTHONPATH
3. Mejora la UX con comandos nativos (`meridian`, `meridian-mcp`)
4. Funciona con todos los clientes MCP sin scripts wrapper
5. Es mantenible a largo plazo

### Siguientes Pasos Sugeridos

1. **Inmediato:** Implementar Opción C en rama feature
2. **Testing:** Verificar con todos los clientes MCP (Claude Code, VSCode, OpenCode)
3. **Documentación:** Actualizar CLAUDE.md y README.md con nueva instalación
4. **Rollout:** Merge a main y notificar al equipo

---

## 8. Referencias

1. `pyproject.toml` - Configuración de build e instalación
2. `src/meridian/__init__.py` - Package initialization
3. `src/meridian/__main__.py` - CLI entry point
4. `src/meridian/server.py` - FastMCP server implementation
5. `scripts/install.sh` - Script de instalación y configuración MCP
6. `opencode.json` - Configuración OpenCode MCP
7. `CLAUDE.md` - Documentación del proyecto
8. PEP 660 - Editable installs para pyproject.toml
9. Hatchling documentation - Editable install modes

---

*Fin del Reporte Técnico*
