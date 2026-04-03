"""Compatibility wrapper for the packaged utility module."""

from vehicle_counter.utils import draw_bounding_boxes, load_video, save_video

__all__ = ["load_video", "save_video", "draw_bounding_boxes"]
