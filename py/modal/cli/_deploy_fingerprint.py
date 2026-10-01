# Copyright Modal Labs 2026
"""Opt-in local deployment fingerprint for the CLI experiment."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def deployment_fingerprint(paths: tuple[Path, ...], context: dict[str, str]) -> str:
    files = sorted({path.resolve() for path in paths})
    payload = {
        "context": context,
        "files": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in files
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_matches(cache_path: Path, fingerprint: str) -> bool:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(data, dict) and data.get("schema") == 1 and data.get("fingerprint") == fingerprint


def save_fingerprint(cache_path: Path, fingerprint: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=cache_path.parent, prefix=f".{cache_path.name}-", delete=False
        ) as output:
            temporary_path = Path(output.name)
            json.dump({"schema": 1, "fingerprint": fingerprint}, output)
            output.write("\n")
        os.replace(temporary_path, cache_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
