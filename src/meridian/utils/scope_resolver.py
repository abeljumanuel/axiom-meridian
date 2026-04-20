"""Scope hierarchy resolution and dynamic attribute filtering."""

import sqlite3


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
    # Normalizar project_id: si no existe pero "project-<id>" sí, usarlo
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
    """
    SELECT key, value FROM scope_attributes WHERE scope_id = ?
    Retorna dict: {"framework": "quarkus", "component_role": "gateway"}
    Si no hay atributos → retorna dict vacío.
    """
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
            # Si el key no existe en project_attributes → inclusión conservadora

        if include:
            result.append(rule_id)

    return result
