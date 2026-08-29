from __future__ import annotations

from os import PathLike

from dotenv import load_dotenv


def load_runtime_environment(dotenv_path: str | PathLike[str] | None = None) -> None:
    """Load missing runtime settings without overriding explicit process values."""
    load_dotenv(dotenv_path=dotenv_path, override=False)
