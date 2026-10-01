"""Small app for testing the fork's opt-in local deployment fingerprint."""

import modal

app = modal.App("mini-modal-fingerprint-probe-20261001")


@app.function()
def increment(value: int) -> int:
    return value + 4


@app.function()
def revision() -> str:
    return "third-deployment"
