"""Convenience entry point for the maintained Django service.

Examples:
    python main.py check
    python main.py test
    python main.py runserver 127.0.0.1:8000

The original interactive prototype was removed from this entry point because it
depended on absent paths/weights, displayed identity images in GUI windows, and
printed extracted identity data. Its audit is retained in docs/current-state.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    repository_root = Path(__file__).resolve().parent
    django_root = repository_root / "Django Api"
    sys.path.insert(0, str(django_root))
    # Django's test discovery and relative management-command arguments should
    # behave exactly as when manage.py is invoked from its project directory.
    os.chdir(django_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")

    from django.core.management import execute_from_command_line

    arguments = sys.argv if len(sys.argv) > 1 else [sys.argv[0], "help"]
    execute_from_command_line(arguments)


if __name__ == "__main__":
    main()
