"""Configuration — environment variables and platform detection."""

import os
import platform
import sys
from pathlib import Path


def _get_default_kb_path() -> Path:
    """Retorna la ruta por defecto del knowledge base según el sistema operativo."""
    if sys.platform == "darwin":
        return Path("~/Library/Application Support/meridian").expanduser()
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", os.path.expanduser("~"))).resolve() / "meridian"
    else:
        return Path("~/.local/share/meridian").expanduser()


def _ensure_kb_structure(path: Path) -> None:
    """Crea la estructura de directorios del knowledge base si no existe."""
    kb_subdirs = [
        "knowledge-base/global",
        "knowledge-base/projects",
        "lessons/global",
        "lessons/projects",
    ]
    for subdir in kb_subdirs:
        full_path = path / subdir
        full_path.mkdir(parents=True, exist_ok=True)
    (path / "meridian.db").touch()


def get_knowledge_base_path() -> Path:
    raw = os.environ.get("KNOWLEDGE_BASE_PATH")
    if not raw:
        path = _get_default_kb_path()
    else:
        path = Path(raw).resolve()

    if not path.is_dir():
        _ensure_kb_structure(path)

    kb_subdirs = ["knowledge-base", "lessons"]
    missing = [d for d in kb_subdirs if not (path / d).is_dir()]
    if missing:
        _ensure_kb_structure(path)

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
