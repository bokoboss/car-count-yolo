"""Compatibility wrapper for the packaged config module."""

from src.vehicle_counter.config import (
    CONFIDENCE_THRESHOLD,
    FRAME_SKIP,
    LINE_POSITION,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)

__all__ = [
    "CONFIDENCE_THRESHOLD",
    "FRAME_SKIP",
    "LINE_POSITION",
    "WINDOW_TITLE",
    "WINDOW_WIDTH",
    "WINDOW_HEIGHT",
]
