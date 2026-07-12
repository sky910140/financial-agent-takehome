from __future__ import annotations

import hashlib
from pathlib import Path


def normalized_text_sha256(path: Path) -> str:
    """Hash repository text content independently of CRLF versus LF checkout style."""
    canonical_bytes = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(canonical_bytes).hexdigest()
