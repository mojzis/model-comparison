"""Parse AA model names into (family, effort, reasoning).

The free tier has no effort field, so effort comes from the name's trailing
parenthetical. Formats seen in the wild:

    GPT-6.1 Sol (xhigh)                    GPT-6 Luna (Non-reasoning)
    Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)
    Claude Fable 5 (Adaptive Reasoning, Max Effort, Opus 4.8 Fallback)
    Claude Sonnet 5 (Non-reasoning, High Effort)
    Claude 4.5 Haiku (Reasoning)           o3
    GPT-5.5 Instant (June 2026)            <- not an effort parenthetical
"""

import re
from dataclasses import dataclass

EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "default"  # model has no effort variants
EFFORT_ORDER = (*EFFORTS, DEFAULT_EFFORT)
# "minimal" (old GPT-5 models only) is parsed but, not being in EFFORT_ORDER,
# dropped by tidy.select_current.

_TRAILING_PARENS = re.compile(r"^(?P<base>.*?)\s*\((?P<inner>[^()]*)\)\s*$")
_EFFORT_TOKEN = re.compile(
    r"^(?P<effort>minimal|low|medium|high|xhigh|max)(?:\s+effort)?$", re.IGNORECASE
)
_FALLBACK_TOKEN = re.compile(r"\bfallback$", re.IGNORECASE)
_REASONING_TOKENS = {"reasoning": True, "adaptive reasoning": True, "thinking": True}
_NON_REASONING_TOKENS = {"non-reasoning", "non reasoning"}
# "Claude 4.5 Haiku" -> "Haiku 4.5" to match the newer "Claude Opus 5.5" order.
_OLD_CLAUDE_ORDER = re.compile(r"^(?P<ver>\d+(?:\.\d+)?)\s+(?P<tier>[A-Z][a-z]+)$")


@dataclass(frozen=True)
class ParsedName:
    family: str
    effort: str  # one of EFFORT_ORDER, or "minimal"
    reasoning: bool


def _classify(inner: str) -> tuple[str | None, bool | None] | None:
    """Read a parenthetical as (effort, reasoning); None if it isn't effort-ish."""
    effort: str | None = None
    reasoning: bool | None = None
    for raw in inner.split(","):
        tok = raw.strip().lower()
        if m := _EFFORT_TOKEN.match(tok):
            effort = m.group("effort")
        elif tok in _NON_REASONING_TOKENS:
            reasoning = False
        elif tok in _REASONING_TOKENS:
            reasoning = True
        elif _FALLBACK_TOKEN.search(tok):
            continue
        else:
            return None  # e.g. "June 2026", "Preview", "Nov '24"
    return effort, reasoning


def family_name(base: str) -> str:
    """Strip the "Claude " prefix and normalize old "4.5 Haiku" ordering."""
    name = base.strip()
    rest = name.removeprefix("Claude ")
    if rest == name or (rest[:1].isdigit() and not _OLD_CLAUDE_ORDER.match(rest)):
        return name  # not Claude, or a bare "Claude 2.0"
    if m := _OLD_CLAUDE_ORDER.match(rest):
        return f"{m.group('tier')} {m.group('ver')}"
    return rest


def parse_name(name: str) -> ParsedName:
    base, classified = name, None
    if m := _TRAILING_PARENS.match(name):
        classified = _classify(m.group("inner"))
        if classified is not None:
            base = m.group("base")
    effort, reasoning = classified or (None, None)
    return ParsedName(
        family=family_name(base),
        effort=effort or DEFAULT_EFFORT,
        reasoning=reasoning is not False,
    )
