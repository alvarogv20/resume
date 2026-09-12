"""Resolve tools consistently, including executables installed beside venv Python."""
import os
from pathlib import Path
import shutil
import sys


def resolve_tool(name, explicit=None):
    override = explicit or os.environ.get(name.upper() + '_BIN')
    if override:
        found = shutil.which(override)
    else:
        found = shutil.which(name)
        if not found:
            sibling = Path(sys.executable).resolve().parent / (name + ('.exe' if os.name == 'nt' else ''))
            found = shutil.which(str(sibling))
    if not found:
        raise ValueError(f'{name} executable missing; install it or set {name.upper()}_BIN.')
    return str(Path(found).resolve())
