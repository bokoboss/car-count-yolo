from pathlib import Path

import cv2
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def is_supported_video_file(path):
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def load_video(path):
    if not path:
        return None, "No file was selected."

    if not is_supported_video_file(path):
        return None, "Unsupported file type. Please choose an MP4, AVI, MOV, or MKV video."

    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        return None, "The selected file could not be opened as a video."

    return capture, None


def read_first_frame(capture):
    if capture is None:
        return None, "Video is not loaded."

    success, frame = capture.read()
    if not success or frame is None:
        return None, "The first frame could not be read from the video."

    return frame, None


def frame_to_pixmap(frame):
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb_frame.shape
    bytes_per_line = channels * width
    image = QImage(
        rgb_frame.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(image.copy())


def draw_line_overlay(pixmap, start_point, end_point):
    annotated_pixmap = pixmap.copy()
    painter = QPainter(annotated_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    line_pen = QPen(QColor("#ff3b30"), 3)
    painter.setPen(line_pen)
    painter.drawLine(start_point, end_point)

    point_pen = QPen(QColor("#ffffff"), 2)
    painter.setPen(point_pen)
    painter.setBrush(QColor("#ff3b30"))
    point_radius = 6
    painter.drawEllipse(start_point, point_radius, point_radius)
    painter.drawEllipse(end_point, point_radius, point_radius)

    painter.end()
    return annotated_pixmap


def save_video(frames, path):
    pass


def draw_bounding_boxes(frame, detections):
    return frame
