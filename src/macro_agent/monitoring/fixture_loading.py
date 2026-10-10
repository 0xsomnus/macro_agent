"""Bounded operator fixture selection shared by the internal runner commands."""

import json

from macro_agent.domain.models import normalize_json_object
from .sources import load_recorded


def fixture_loaders(path):
    if path is None:
        return {}
    try:
        with path.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError
        mapping = json.loads(normalize_json_object(raw.decode("utf-8")))
        if not mapping or any(type(key) is not str or not key.startswith("fixture-")
                or type(value) is not str or not value for key, value in mapping.items()):
            raise ValueError
        return {key: (lambda value=value: load_recorded(value)) for key, value in mapping.items()}
    except (ValueError, TypeError, OSError):
        raise ValueError("Fixture map requires bounded fixture-source to local-file entries") from None
