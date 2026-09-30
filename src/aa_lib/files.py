"""Atomic file writes and dated-snapshot lookup."""

import os
import re
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})$")


def write_atomic(path: Path, writer: Callable[[Path], object]) -> None:
    """Call `writer(tmp)` on a temp file next to `path`, then rename it into place.

    A reader never sees a half-written file, and a failed write leaves the old one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        writer(tmp)
        tmp.chmod(0o644)  # mkstemp creates 0600
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def write_text_atomic(path: Path, text: str) -> None:
    write_atomic(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def dated_files(directory: Path, suffix: str) -> dict[date, Path]:
    """Files named YYYY-MM-DD<suffix> in `directory`, keyed by date."""
    found = {}
    for p in directory.glob(f"*{suffix}"):
        m = _DATED.match(p.name.removesuffix(suffix))
        if m:
            found[date.fromisoformat(m.group(1))] = p
    return found
