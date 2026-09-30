import json

import pytest

from aa_lib.parse import ParsedName, parse_name
from tests.conftest import FIXTURE

# Real names from data/raw/sample.json (AA free API, 2026-09-30).
CASES = [
    ("GPT-6.1 Sol (xhigh)", "GPT-6.1 Sol", "xhigh", True),
    ("GPT-6.1 Sol (max)", "GPT-6.1 Sol", "max", True),
    ("GPT-6 Luna (low)", "GPT-6 Luna", "low", True),
    ("GPT-6 Luna (Non-reasoning)", "GPT-6 Luna", "default", False),
    ("GPT-5.4 mini (Non-Reasoning)", "GPT-5.4 mini", "default", False),
    ("GPT-5.6 Terra (medium)", "GPT-5.6 Terra", "medium", True),
    ("GPT-5 (minimal)", "GPT-5", "minimal", True),
    ("gpt-oss-120b (high)", "gpt-oss-120b", "high", True),
    ("o3", "o3", "default", True),
    ("GPT-5.5 Instant (June 2026)", "GPT-5.5 Instant (June 2026)", "default", True),
    ("GPT-4o (Nov '24)", "GPT-4o (Nov '24)", "default", True),
    (
        "Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)",
        "Opus 5.5",
        "max",
        True,
    ),
    (
        "Claude Sonnet 5.5 (Adaptive Reasoning, Xhigh Effort, Default Fallback)",
        "Sonnet 5.5",
        "xhigh",
        True,
    ),
    (
        "Claude Fable 5 (Adaptive Reasoning, Max Effort, Opus 4.8 Fallback)",
        "Fable 5",
        "max",
        True,
    ),
    ("Claude Opus 5 (Adaptive Reasoning, Low Effort)", "Opus 5", "low", True),
    ("Claude Sonnet 5 (Non-reasoning, High Effort)", "Sonnet 5", "high", False),
    ("Claude 4.5 Haiku (Reasoning)", "Haiku 4.5", "default", True),
    ("Claude 4.5 Haiku (Non-reasoning)", "Haiku 4.5", "default", False),
    ("Claude 3 Opus", "Opus 3", "default", True),
    ("Claude 2.0", "Claude 2.0", "default", True),
    ("Claude 3.5 Sonnet (Oct '24)", "Claude 3.5 Sonnet (Oct '24)", "default", True),
]


@pytest.mark.parametrize(("name", "family", "effort", "reasoning"), CASES)
def test_parse_name(name: str, family: str, effort: str, reasoning: bool) -> None:
    assert parse_name(name) == ParsedName(family, effort, reasoning)


def test_cases_are_real_names() -> None:
    names = {m["name"] for m in json.loads(FIXTURE.read_text())["data"]}
    assert {c[0] for c in CASES} <= names
