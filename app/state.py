"""Backward-compatible placeholder for modules that previously imported app.state."""

from __future__ import annotations

from app.runtime import AppRuntime

runtime: AppRuntime | None = None

__all__ = ["runtime"]
