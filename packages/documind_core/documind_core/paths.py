"""
Canonical filesystem paths for the documind monorepo.

All paths are resolved relative to this file's location so they are
correct regardless of the current working directory or how the package
was installed.

Layout assumed:
    <repo_root>/
    ├── packages/
    │   └── documind_core/
    │       └── documind_core/
    │           └── paths.py   ← this file
    └── data/
"""

from pathlib import Path

# packages/documind_core/documind_core/  →  up 3 levels  →  repo root
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

# <repo_root>/data/  – all persistent runtime data lives here
DATA_DIR: Path = REPO_ROOT / "data"

# Convenience sub-paths
SQLITE_DIR: Path = DATA_DIR          # sqlite DB sits directly in data/
QDRANT_STORAGE_DIR: Path = DATA_DIR / "qdrant_storage"
UPLOADS_DIR: Path = DATA_DIR / "uploads"
LOGS_DIR: Path = DATA_DIR / "logs"


def ensure_dirs() -> None:
    """Create all runtime data directories if they don't exist yet."""
    for directory in (
        DATA_DIR,
        QDRANT_STORAGE_DIR,
        UPLOADS_DIR,
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
