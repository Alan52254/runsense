"""Who is speaking, kept apart from what the system enforces.

Each persona is a folder: SOUL.md says who it is and how it talks, and
skills/<name>.md says how to do one job (often the JSON shape to emit).
The two AI surfaces never share a persona:

  health_coach     the Athlete's private AI 健康教練. Explains, and may
                   *suggest* a day's training -- always the reviewed
                   engine's candidates, never a workout it wrote.
  team_assistant   RunSense助手 in the team chat. Turns a coach's own
                   plan into a card the coach confirms, records an
                   athlete's body report, answers general questions.

These files shape wording only. Nothing that keeps an athlete safe lives
here: Safety Triage, the numbers-must-be-in-the-source checks, who may
schedule and whether a coach has locked a day are all enforced in code
(ADR 0001, ADR 0003), so a SOUL.md that is missing, empty or rewritten
cannot make the system less safe -- only change how it sounds.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

logger = logging.getLogger("app.personas")

Persona = Literal["health_coach", "team_assistant"]

_ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def soul(persona: Persona) -> str:
    """The persona's SOUL.md; empty (and logged) when the file is missing."""
    path = _ROOT / persona / "SOUL.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("persona_soul_missing persona=%s", persona)
        return ""


@lru_cache(maxsize=None)
def skill(persona: Persona, name: str) -> str:
    """One skill's instructions. A missing skill is a deployment error --
    it usually defines the output shape a caller parses -- so it raises."""
    return (_ROOT / persona / "skills" / f"{name}.md").read_text(encoding="utf-8").strip()


def system_prompt(persona: Persona, skill_name: str, *, with_soul: bool = True) -> str:
    """The system message for one call: the persona's voice, then the job.

    Extraction-only skills (they emit JSON, not prose) pass with_soul=False:
    a voice has nothing to add there, and keeping it out means rewriting a
    SOUL.md cannot change what gets extracted.
    """
    job = skill(persona, skill_name)
    voice = soul(persona) if with_soul else ""
    return f"{voice}\n\n{job}" if voice else job
