"""Filesystem anchors for repository-owned files.

CI checks this repository out into a `maintenance/` directory and runs pytest
from its parent, so paths written relative to the caller's working directory
happen to resolve there and nowhere else — not from the repository root, and not
from a clone whose directory carries a different name. Anchor on the package
instead, which is the checkout root.
"""

from __future__ import annotations

from pathlib import Path

#: The repository checkout root: the directory holding this package.
REPO_ROOT = Path(__file__).resolve().parent
