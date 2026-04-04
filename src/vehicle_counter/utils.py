from pathlib import Path
from urllib.parse import urlparse
import math

import cv2
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def is_supported_video_file(path):
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def is_remote_video_source(path):
    parsed = urlparse((path or "").strip())
    return parsed.scheme in {"http", "https"}


def is_direct_stream_url(path):
    parsed = urlparse((path or "").strip())
    return parsed.scheme in {"http", "https", "rtsp"}


def open_video_capture(path, is_live=False, prioritize_low_latency=False):
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        return None, "The video stream could not be opened."

    if is_live and prioritize_low_latency:
        try_set_capture_property(capture, cv2.CAP_PROP_BUFFERSIZE, 1)

    return capture, None


def load_video(path, is_live=False, prioritize_low_latency=False):
    if not path:
        return None, "No video source was provided."

    if is_direct_stream_url(path):
        return open_video_capture(
            path,
            is_live=is_live,
            prioritize_low_latency=prioritize_low_latency,
        )

    if not is_supported_video_file(path):
        return None, "Unsupported file type. Please choose an MP4, AVI, MOV, or MKV video."

    capture, error_message = open_video_capture(path)
    if error_message:
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


def build_video_writer(output_path, frame_size, fps):
    width, height = frame_size
    if width <= 0 or height <= 0:
        return None, "Annotated video could not be created because the frame size is invalid."

    output_path = str(output_path)
    suffix = Path(output_path).suffix.lower()
    codec_candidates = get_video_writer_codec_candidates(suffix)
    for codec_name in codec_candidates:
        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*codec_name),
            max(float(fps or 20.0), 1.0),
            (int(width), int(height)),
        )
        if writer.isOpened():
            return writer, None
        writer.release()

    return None, "Annotated video could not be created with the available video codecs."


def get_video_writer_codec_candidates(suffix):
    if suffix == ".avi":
        return ("XVID", "MJPG")
    return ("mp4v", "avc1", "XVID", "MJPG")


def draw_line_overlay(
    pixmap,
    start_point,
    end_point,
    direction_labels=None,
    line_color="#ff3b30",
    line_label=None,
    is_selected=False,
    show_direction_legend=False,
    show_line_label=True,
    show_handles=True,
    active_handle=None,
):
    annotated_pixmap = pixmap.copy()
    painter = QPainter(annotated_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    start_x = start_point.x()
    start_y = start_point.y()
    end_x = end_point.x()
    end_y = end_point.y()
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    line_length = math.hypot(delta_x, delta_y) or 1.0
    tangent_x = delta_x / line_length
    tangent_y = delta_y / line_length
    normal_x = -delta_y / line_length
    normal_y = delta_x / line_length

    base_color = QColor(line_color)
    if not is_selected:
        base_color.setAlpha(150)

    line_pen = QPen(base_color, 5 if is_selected else 2)
    painter.setPen(line_pen)
    painter.drawLine(start_point, end_point)

    midpoint_x = (start_x + end_x) / 2.0
    midpoint_y = (start_y + end_y) / 2.0
    side_offset = min(max(line_length * 0.18, 38.0), 72.0)

    side_a_point = QPoint(
        round(midpoint_x - normal_x * side_offset),
        round(midpoint_y - normal_y * side_offset),
    )
    side_b_point = QPoint(
        round(midpoint_x + normal_x * side_offset),
        round(midpoint_y + normal_y * side_offset),
    )

    direction_color = QColor(base_color)
    direction_pen = QPen(direction_color, 2 if is_selected else 1)
    painter.setPen(direction_pen)
    painter.drawLine(side_a_point, side_b_point)
    draw_arrow_head(
        painter,
        side_b_point,
        tangent_x=normal_x,
        tangent_y=normal_y,
        color=direction_color,
    )

    draw_side_badge(
        painter,
        side_a_point,
        "A",
        QColor("#ff9f0a"),
        is_selected=is_selected,
    )
    draw_side_badge(
        painter,
        side_b_point,
        "B",
        QColor("#34c759"),
        is_selected=is_selected,
    )
    if line_label and show_line_label:
        draw_line_badge(
            painter,
            QPoint(round(midpoint_x), round(midpoint_y)),
            line_label,
            QColor(line_color),
            is_selected=is_selected,
        )

    if direction_labels and show_direction_legend:
        draw_direction_legend(
            painter,
            midpoint_x=midpoint_x + tangent_x * 46.0,
            midpoint_y=midpoint_y + tangent_y * 46.0,
            lines=(
                f"{direction_labels['negative_to_positive']} = A -> B",
                f"{direction_labels['positive_to_negative']} = B -> A",
            ),
            bounds=annotated_pixmap.rect(),
        )

    if show_handles:
        draw_endpoint_handle(
            painter,
            start_point,
            QColor("#ffd60a") if active_handle == "start" else QColor("#ffffff"),
            is_selected=is_selected,
        )
        draw_endpoint_handle(
            painter,
            end_point,
            QColor("#ffd60a") if active_handle == "end" else QColor("#ffffff"),
            is_selected=is_selected,
        )

    painter.end()
    return annotated_pixmap


def draw_review_overlay(
    frame,
    line_points_by_key,
    direction_labels_by_line,
    line_colors,
    line_short_names,
    counts_snapshot,
):
    annotated_frame = frame.copy()
    for line_key, line_points in (line_points_by_key or {}).items():
        if not line_points:
            continue
        color = hex_to_bgr(line_colors.get(line_key, "#ff3b30"))
        start_point = (int(line_points[0].x()), int(line_points[0].y()))
        end_point = (int(line_points[1].x()), int(line_points[1].y()))
        cv2.line(annotated_frame, start_point, end_point, color, 3, cv2.LINE_AA)
        draw_review_line_label(
            annotated_frame,
            line_short_names.get(line_key, line_key),
            start_point,
            end_point,
            color,
        )

    draw_review_summary_overlay(
        annotated_frame,
        counts_snapshot or {},
        direction_labels_by_line or {},
        line_short_names or {},
    )
    return annotated_frame


def draw_review_line_label(frame, line_label, start_point, end_point, color):
    midpoint = (
        int((start_point[0] + end_point[0]) / 2),
        int((start_point[1] + end_point[1]) / 2),
    )
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.52
    thickness = 1
    text_size, _ = cv2.getTextSize(line_label, font, scale, thickness)
    box_width = text_size[0] + 14
    box_height = text_size[1] + 10
    left = max(8, midpoint[0] - (box_width // 2))
    top = max(8, midpoint[1] - box_height - 10)
    cv2.rectangle(
        frame,
        (left, top),
        (left + box_width, top + box_height),
        color,
        -1,
    )
    cv2.rectangle(
        frame,
        (left, top),
        (left + box_width, top + box_height),
        (20, 20, 20),
        1,
    )
    cv2.putText(
        frame,
        line_label,
        (left + 7, top + box_height - 7),
        font,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def draw_review_summary_overlay(frame, counts_snapshot, direction_labels_by_line, line_short_names):
    total = int(counts_snapshot.get("total", 0))
    processed_frames = int(counts_snapshot.get("processed_frames", 0))
    line_results = counts_snapshot.get("line_results", {})
    lines = [
        f"Total: {total}",
        f"Frames: {processed_frames}",
    ]
    for line_key, line_result in line_results.items():
        direction_a_total = sum(
            line_result.get("direction_counts", {})
            .get("negative_to_positive", {})
            .values()
        )
        direction_b_total = sum(
            line_result.get("direction_counts", {})
            .get("positive_to_negative", {})
            .values()
        )
        line_name = line_short_names.get(line_key, line_key)
        lines.append(
            f"{line_name}  T:{line_result.get('total', 0)}  A:{direction_a_total}  B:{direction_b_total}"
        )

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.52
    thickness = 1
    line_height = 20
    max_width = 0
    for text in lines:
        text_size, _ = cv2.getTextSize(text, font, scale, thickness)
        max_width = max(max_width, text_size[0])
    box_width = max_width + 18
    box_height = len(lines) * line_height + 14
    left = 12
    top = 12
    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (left, top),
        (left + box_width, top + box_height),
        (255, 255, 255),
        -1,
    )
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    cv2.rectangle(
        frame,
        (left, top),
        (left + box_width, top + box_height),
        (34, 34, 34),
        1,
    )
    for index, text in enumerate(lines):
        y = top + 22 + index * line_height
        cv2.putText(
            frame,
            text,
            (left + 8, y),
            font,
            scale,
            (25, 25, 25),
            thickness,
            cv2.LINE_AA,
        )


def render_tracking_preview_frame(result, model, track_label_mode="off"):
    base_frame = result.plot(labels=False, conf=False)
    if track_label_mode == "off":
        return base_frame
    if result.boxes is None or result.boxes.cls is None:
        return base_frame

    track_ids = (
        result.boxes.id.int().tolist()
        if result.boxes.id is not None
        else [None] * len(result.boxes.cls)
    )
    class_ids = result.boxes.cls.int().tolist()
    boxes = result.boxes.xyxy.tolist()
    for track_id, class_id, box in zip(track_ids, class_ids, boxes):
        class_name = str(model.names[int(class_id)])
        draw_compact_track_label(
            base_frame,
            box=box,
            class_name=class_name,
            track_id=track_id,
            track_label_mode=track_label_mode,
        )
    return base_frame


def draw_compact_track_label(frame, box, class_name, track_id, track_label_mode):
    label_text = class_name
    if track_label_mode == "id_class" and track_id is not None:
        label_text = f"{track_id} {class_name}"

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.36
    thickness = 1
    text_size, _ = cv2.getTextSize(label_text, font, scale, thickness)
    left = max(6, int(box[0]))
    top = max(6, int(box[1]) - text_size[1] - 8)
    right = left + text_size[0] + 8
    bottom = top + text_size[1] + 6

    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (left, top),
        (right, bottom),
        (255, 255, 255),
        -1,
    )
    cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)
    cv2.rectangle(frame, (left, top), (right, bottom), (80, 80, 80), 1)
    cv2.putText(
        frame,
        label_text,
        (left + 4, bottom - 4),
        font,
        scale,
        (35, 35, 35),
        thickness,
        cv2.LINE_AA,
    )


def draw_endpoint_handle(painter, point, fill_color, is_selected=False):
    outer_radius = 8 if is_selected else 6
    inner_radius = 4
    painter.setPen(QPen(QColor("#111111"), 2 if is_selected else 1))
    painter.setBrush(fill_color)
    painter.drawEllipse(point, outer_radius, outer_radius)
    painter.setPen(QPen(QColor("#ff3b30"), 1))
    painter.setBrush(QColor("#ff3b30"))
    painter.drawEllipse(point, inner_radius, inner_radius)


def draw_side_badge(painter, point, text, fill_color, is_selected=False):
    font = QFont()
    font.setBold(True)
    font.setPointSize(10 if is_selected else 9)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    width = max(24, metrics.horizontalAdvance(text) + 14)
    height = metrics.height() + 8
    left = point.x() - (width // 2)
    top = point.y() - (height // 2)
    fill = QColor(fill_color)
    if not is_selected:
        fill.setAlpha(185)
    painter.setPen(QPen(QColor("#111111"), 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(left, top, width, height, 8, 8)
    painter.setPen(QColor("#111111"))
    painter.drawText(
        left,
        top,
        width,
        height,
        int(Qt.AlignmentFlag.AlignCenter),
        text,
    )


def draw_line_badge(painter, point, text, fill_color, is_selected=False):
    font = QFont()
    font.setBold(True)
    font.setPointSize(9 if is_selected else 8)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    width = max(34, metrics.horizontalAdvance(text) + 16)
    height = metrics.height() + 8
    left = point.x() - (width // 2)
    top = point.y() - (height // 2)
    fill = QColor(fill_color)
    if not is_selected:
        fill.setAlpha(185)
    painter.setPen(QPen(QColor("#111111"), 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(left, top, width, height, 8, 8)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(
        left,
        top,
        width,
        height,
        int(Qt.AlignmentFlag.AlignCenter),
        text,
    )


def draw_arrow_head(painter, tip_point, tangent_x, tangent_y, color):
    arrow_length = 10.0
    wing_length = 5.0
    base_x = tip_point.x() - tangent_x * arrow_length
    base_y = tip_point.y() - tangent_y * arrow_length
    left_x = base_x - tangent_y * wing_length
    left_y = base_y + tangent_x * wing_length
    right_x = base_x + tangent_y * wing_length
    right_y = base_y - tangent_x * wing_length
    painter.setPen(QPen(color, 2))
    painter.drawLine(tip_point, QPoint(round(left_x), round(left_y)))
    painter.drawLine(tip_point, QPoint(round(right_x), round(right_y)))


def draw_direction_legend(painter, midpoint_x, midpoint_y, lines, bounds):
    font = QFont()
    font.setPointSize(8)
    font.setBold(True)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    line_height = metrics.height()
    text_width = max(metrics.horizontalAdvance(line) for line in lines) + 12
    box_width = min(max(156, text_width), bounds.width() - 24)
    box_height = line_height * len(lines) + 10
    left = round(midpoint_x - (box_width / 2))
    top = round(midpoint_y - (box_height / 2))
    left = max(12, min(left, bounds.width() - box_width - 12))
    top = max(12, min(top, bounds.height() - box_height - 12))

    painter.setPen(QPen(QColor(17, 17, 17, 170), 1))
    painter.setBrush(QColor(255, 255, 255, 170))
    painter.drawRoundedRect(left, top, box_width, box_height, 8, 8)

    painter.setPen(QColor("#111111"))
    for index, line in enumerate(lines):
        text_top = top + 5 + index * line_height
        painter.drawText(left + 6, text_top + metrics.ascent(), line)


def save_video(frames, path):
    pass


def draw_bounding_boxes(frame, detections):
    return frame


def try_set_capture_property(capture, property_id, value):
    try:
        capture.set(property_id, value)
    except Exception:
        return False
    return True


def hex_to_bgr(color_value):
    normalized = (color_value or "#ff3b30").lstrip("#")
    if len(normalized) != 6:
        normalized = "ff3b30"
    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    return blue, green, red
