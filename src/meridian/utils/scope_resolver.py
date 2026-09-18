"""Scope hierarchy resolution and dynamic attribute filtering."""

import sqlite3


def resolve_scope_hierarchy(conn: sqlite3.Connection, project_id: str) -> list[str]:
    """
    Retorna la cadena de scopes ordenada por precedencia: [project, parent, ..., global].

    Lanza ValueError si project_id no existe en scopes (listando los scopes válidos)
    o si la jerarquía de parent_id contiene un ciclo.
    """
    # Los IDs de proyecto pueden llegar sin el prefijo "project-"; se acepta la forma
    # corta como alias de conveniencia cuando la forma prefijada existe en scopes.
    cursor = conn.execute("SELECT id FROM scopes WHERE id = ?", (project_id,))
    if cursor.fetchone() is None:
        candidate = f"project-{project_id}"
        cursor = conn.execute("SELECT id FROM scopes WHERE id = ?", (candidate,))
        if cursor.fetchone():
            project_id = candidate
        else:
            valid_cursor = conn.execute("SELECT id FROM scopes ORDER BY id")
            valid_scopes = [row[0] for row in valid_cursor.fetchall()]
            raise ValueError(
                f"Scope '{project_id}' not found. Valid scopes: {valid_scopes}"
            )

    chain: list[str] = []
    visited: set[str] = set()
    current: str | None = project_id
    while current is not None:
        if current in visited:
            raise ValueError(
                f"Circular scope hierarchy detected at '{current}'"
            )
        visited.add(current)
        chain.append(current)
        cursor = conn.execute(
            "SELECT parent_id FROM scopes WHERE id = ?", (current,)
        )
        row = cursor.fetchone()
        current = row[0] if row is not None else None
    return chain


def load_scope_attributes(conn: sqlite3.Connection, scope_id: str) -> dict[str, str]:
    """Retorna los atributos dinámicos del scope (ADR-002), o {} si no tiene ninguno."""
    cursor = conn.execute(
        "SELECT key, value FROM scope_attributes WHERE scope_id = ?",
        (scope_id,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def filter_by_attributes(
    conn: sqlite3.Connection,
    rule_ids: list[str],
    project_attributes: dict[str, str],
) -> list[str]:
    """
    Filtra rule_ids por compatibilidad de atributos con el proyecto (ADR-002).

    Una regla sin atributos propios aplica a todos los proyectos. Una regla con
    atributos se incluye solo si ninguno de ellos contradice project_attributes;
    un atributo de la regla ausente en el proyecto se trata como compatible
    (inclusión conservadora) para evitar que el proyecto pierda conocimiento
    por simple falta de metadata.
    """
    if not rule_ids:
        return []

    result: list[str] = []
    for rule_id in rule_ids:
        cursor = conn.execute(
            "SELECT key, value FROM rule_attributes WHERE rule_id = ?",
            (rule_id,),
        )
        rule_attrs = {row[0]: row[1] for row in cursor.fetchall()}

        if not rule_attrs:
            result.append(rule_id)
            continue

        include = True
        for key, value in rule_attrs.items():
            if key in project_attributes:
                if project_attributes[key] != value:
                    include = False
                    break
            # key ausente en project_attributes: se deja `include` intacto a propósito
            # (ver docstring — inclusión conservadora, no un caso sin manejar)

        if include:
            result.append(rule_id)

    return result
