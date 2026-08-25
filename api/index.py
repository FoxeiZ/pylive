from __future__ import annotations

import sys
from pathlib import Path

# ensure root and src are on python path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.app import create_app  # noqa: E402

app = create_app()
