"""Compatibility entry point for the shared fictional fixture builder."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.lab.fixtures import correction_pin, fixture_case  # noqa: E402,F401
