"""Exercise the reduced-source artifact on Modal's existing backend."""

from pathlib import Path

import modal
from modal.experimental.ast_artifact import ast_function

app = modal.App("mini-modal-ast-fingerprint-probe-20261001")


def unrelated(value: int) -> int:
    return value - 2000


@ast_function(app, cache_dir=Path(__file__).resolve().parents[1] / ".venv" / "ast-artifacts")
def compute(value: int) -> int:
    from ast_probe_helpers import multiply

    return multiply(value) + 1
