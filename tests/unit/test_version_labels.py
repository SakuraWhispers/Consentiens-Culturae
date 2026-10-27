"""Version-label wiring: every stamp site shares one source of truth.

The labels are manually maintained strings (2026-10-28: scoring v0.1 → v0.2,
after the C4 gate semantic change of 2026-10-23). The historical danger is
one stamp site bumping alone — these pins hold the sites together, and the
default-stamp test keeps the label beside the code that actually changed.
"""

from __future__ import annotations

import inspect

from app.main import create_app
from app.services.decision_engine import SCORING_VERSION
from app.services.robustness import analyze_sensitivity
from app.workflow.coordinator import run_decision


def test_current_scoring_version_is_v0_2() -> None:
    assert SCORING_VERSION == "v0.2"


def test_all_stamp_sites_share_one_source() -> None:
    default = inspect.signature(create_app).parameters["scoring_version"].default
    assert default is SCORING_VERSION, f"create_app default is {default!r}"
    default = inspect.signature(run_decision).parameters["scoring_version"].default
    assert default is SCORING_VERSION, f"run_decision default is {default!r}"
    default = inspect.signature(analyze_sensitivity).parameters["scoring_version"].default
    assert default is SCORING_VERSION, f"analyze_sensitivity default is {default!r}"
