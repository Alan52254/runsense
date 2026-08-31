from __future__ import annotations

import logging
import os
from os import PathLike

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger("app.runtime_env")

# Settings whose value silently changes what the product does rather than
# whether it starts. A stale one inherited from the launching shell produces
# a running server that looks healthy and quietly cannot reach its provider,
# which is expensive to diagnose from the outside.
_SHADOW_SENSITIVE = ("GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GUIDANCE_PROVIDER")


def load_runtime_environment(dotenv_path: str | PathLike[str] | None = None) -> None:
    """Load missing runtime settings without overriding explicit process values.

    A value already in the process environment still wins, so a deployment can
    override the file. But when the two disagree on a setting that decides
    provider behaviour, say so: the file being ignored is otherwise invisible
    until something downstream mysteriously stops working. Only names are
    logged -- never a value, since these are credentials.
    """
    from_file = dotenv_values(dotenv_path=dotenv_path) if dotenv_path else dotenv_values()

    shadowed = [
        name
        for name in _SHADOW_SENSITIVE
        if from_file.get(name) is not None
        and os.environ.get(name) is not None
        and os.environ[name] != from_file[name]
    ]
    if shadowed:
        logger.warning(
            "environment shadows dotenv for %s: the process value is being used "
            "and the file is ignored for these settings",
            ", ".join(shadowed),
        )

    load_dotenv(dotenv_path=dotenv_path, override=False)
