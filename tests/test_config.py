"""Invariants of the live config.toml (the unit tests use a frozen copy)."""

import pytest

from aa_lib.config import Vendor, load_config
from tests.conftest import ROOT

LIVE = load_config(ROOT / "config.toml")


@pytest.mark.parametrize("vendor", LIVE.vendors, ids=lambda v: v.name)
def test_every_allowlisted_family_gets_its_own_style(vendor: Vendor) -> None:
    # family_styles cycles palette and dashes, so a short list would make two
    # families of one vendor look identical.
    assert len(vendor.palette) >= len(vendor.families)
    assert len(LIVE.dashes) >= len(vendor.families)
