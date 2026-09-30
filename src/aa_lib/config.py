"""Load config.toml into a small typed structure."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Vendor:
    name: str  # AA's model_creator.name
    label: str
    palette: tuple[str, ...]
    families: tuple[str, ...]  # empty = keep all


@dataclass(frozen=True)
class Config:
    api_url: str
    timeout_s: float
    data_dir: Path
    out_dir: Path
    title: str
    dashes: tuple[str, ...]
    vendors: tuple[Vendor, ...]

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def tidy_dir(self) -> Path:
        return self.data_dir / "tidy"

    @property
    def chart_html(self) -> Path:
        return self.out_dir / "chart.html"


def load_config(path: Path) -> Config:
    """Read `path`; relative paths resolve against its directory.

    AA_DATA_DIR / AA_OUT_DIR env vars override the configured directories.
    """
    raw = tomllib.loads(path.read_text())
    root = path.parent

    def resolve(env: str, value: str) -> Path:
        p = Path(os.environ.get(env) or value)
        return p if p.is_absolute() else root / p

    vendors = tuple(
        Vendor(
            name=name,
            label=v.get("label", name),
            palette=tuple(v["palette"]),
            families=tuple(v.get("families", [])),
        )
        for name, v in raw["vendors"].items()
    )
    return Config(
        api_url=raw["api"]["url"],
        timeout_s=float(raw["api"].get("timeout_s", 30)),
        data_dir=resolve("AA_DATA_DIR", raw["paths"]["data_dir"]),
        out_dir=resolve("AA_OUT_DIR", raw["paths"]["out_dir"]),
        title=raw["chart"]["title"],
        dashes=tuple(raw["chart"]["dashes"]),
        vendors=vendors,
    )
