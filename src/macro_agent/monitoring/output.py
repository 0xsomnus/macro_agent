"""Escape external control characters and refuse to overwrite a trace."""

import json
import os


def render(value):
    return json.dumps(value, ensure_ascii=True, indent=2)


def save_new(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
