"""Filesystem locations for source, packaged resources, and user data.

During development all three locations are the repository root. The desktop
launcher sets ``VTUBECORD_RESOURCE_DIR`` and ``VTUBECORD_DATA_DIR`` so a
Program Files installation can keep its writable configuration and databases
under the user's local application-data directory.
"""

from __future__ import annotations

import os
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[3]


def resource_root() -> Path:
    configured = os.environ.get("VTUBECORD_RESOURCE_DIR", "").strip()
    return Path(configured).expanduser() if configured else SOURCE_ROOT


def data_root() -> Path:
    configured = os.environ.get("VTUBECORD_DATA_DIR", "").strip()
    return Path(configured).expanduser() if configured else SOURCE_ROOT


def data_path(*parts: str) -> Path:
    return data_root().joinpath(*parts)


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)
