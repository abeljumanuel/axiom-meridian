import re

PRIVATE_PATTERN = re.compile(r"<private>.*?</private>", re.DOTALL)


def strip_private_tags(text: str | None) -> str | None:
    """
    Reemplaza todo contenido entre <private>...</private> con [REDACTED].
    Soporta tags multilínea (re.DOTALL).
    Si text es None, retorna None.
    Si no hay tags, retorna text sin cambios.
    """
    if text is None:
        return None
    return PRIVATE_PATTERN.sub("[REDACTED]", text)
