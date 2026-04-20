"""Configuration — environment variables and platform detection."""

import os
import platform
from pathlib import Path


def get_knowledge_base_path() -> Path:
    raw = os.environ.get("KNOWLEDGE_BASE_PATH")
    if not raw:
        raise RuntimeError(
            "KNOWLEDGE_BASE_PATH environment variable is not set. "
            "Set it to the directory containing your knowledge-base/ and lessons/ folders."
        )
    path = Path(raw).resolve()
    if not path.is_dir():
        raise RuntimeError(
            f"KNOWLEDGE_BASE_PATH={raw} does not exist or is not a directory."
        )
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
