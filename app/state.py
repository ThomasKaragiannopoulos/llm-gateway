"""Backward-compatible proxy to the shared runtime state."""

from app.runtime import state as _runtime_state


def __getattr__(name: str):
    return getattr(_runtime_state, name)
