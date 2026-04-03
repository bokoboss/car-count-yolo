"""Compatibility wrapper for the packaged detection module."""

from vehicle_counter.detection import detect_vehicles, load_model

__all__ = ["load_model", "detect_vehicles"]
