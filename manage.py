"""Django operations for the local desk foundation."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "macro_agent.web.settings")

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
