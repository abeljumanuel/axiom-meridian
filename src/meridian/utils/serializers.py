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
    - str con comillas dobles → escapar con doble comilla: "value ""quoted"" "
    - None → (vacío, sin caracteres)
    - bool → true | false (minúsculas)
    - int/float → representación string directa
    - list → JSON inline: ["tag1","tag2"]
    - Cualquier otro tipo → str(value)
    """

    def _encode_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        s = str(value)
        needs_quote = "," in s or '"' in s
        if '"' in s:
            s = s.replace('"', '""')
        if needs_quote:
            s = f'"{s}"'
        return s

    lines = [f"items[{len(records)}]{{{','.join(fields)}}}:"]
    for record in records:
        row = ",".join(_encode_value(record.get(f)) for f in fields)
        lines.append(f"  {row}")
    return "\n".join(lines)


def serialize(
    records: list[dict[str, Any]],
    format: str = "json",
    fields: list[str] | None = None,
) -> str:
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
