import threading
import time
from pathlib import Path

from .detection import get_target_class_ids, load_model, normalize_settings
from .sources import VideoSource
from .utils import (
    build_video_writer,
    draw_review_overlay,
    is_direct_stream_url,
    is_remote_video_source,
    open_video_capture,
    render_tracking_preview_frame,
)


TRACKER_CONFIG = "bytetrack.yaml"
MOTORCYCLE_TRACKER_CONFIG = Path(__file__).with_name("bytetrack_motorcycle.yaml")
MOTORCYCLE_CLASS_NAME = "motorcycle"
MOTORCYCLE_CROSSING_TOLERANCE_PIXELS = 12.0
DIRECTION_NEGATIVE_TO_POSITIVE = "negative_to_positive"
DIRECTION_POSITIVE_TO_NEGATIVE = "positive_to_negative"
PROCESSING_STATUS_COMPLETED = "completed"
PROCESSING_STATUS_CANCELLED = "cancelled"
PROCESSING_STATUS_ERROR = "error"
PROCESSING_STATUS_STREAM_STOPPED = "stream_stopped"
LIVE_PROGRESS_INTERVAL_SECONDS = 0.35
LIVE_READ_RETRY_DELAY_SECONDS = 0.25
LIVE_READ_FAILURE_GRACE_SECONDS = 4.0
LIVE_READ_FAILURE_REOPEN_THRESHOLD = 1.2
LIVE_MAX_REOPEN_ATTEMPTS = 1
DEFAULT_LINE_KEYS = ("line_1", "line_2", "line_3")


def point_side(point, line_start, line_end):
    return (
        (line_end[0] - line_start[0]) * (point[1] - line_start[1])
        - (line_end[1] - line_start[1]) * (point[0] - line_start[0])
    )


def did_cross_line(previous_point, current_point, line_start, line_end):
    previous_side = point_side(previous_point, line_start, line_end)
    current_side = point_side(current_point, line_start, line_end)

    if previous_side == 0 or current_side == 0:
        return True

    return (previous_side < 0 < current_side) or (current_side < 0 < previous_side)


def get_crossing_direction(previous_point, current_point, line_start, line_end):
    previous_side = point_side(previous_point, line_start, line_end)
    current_side = point_side(current_point, line_start, line_end)

    if previous_side < 0 <= current_side:
        return DIRECTION_NEGATIVE_TO_POSITIVE

    if previous_side > 0 >= current_side:
        return DIRECTION_POSITIVE_TO_NEGATIVE

    if previous_side == 0 and current_side > 0:
        return DIRECTION_NEGATIVE_TO_POSITIVE

    if previous_side == 0 and current_side < 0:
        return DIRECTION_POSITIVE_TO_NEGATIVE

    if current_side == 0 and previous_side < 0:
        return DIRECTION_NEGATIVE_TO_POSITIVE

    if current_side == 0 and previous_side > 0:
        return DIRECTION_POSITIVE_TO_NEGATIVE

    return "unknown"


def get_line_length(line_start, line_end):
    return (
        (line_end[0] - line_start[0]) ** 2
        + (line_end[1] - line_start[1]) ** 2
    ) ** 0.5 or 1.0


def signed_distance_to_line(point, line_start, line_end):
    return point_side(point, line_start, line_end) / get_line_length(line_start, line_end)


def distance_point_to_segment(point, segment_start, segment_end):
    segment_dx = segment_end[0] - segment_start[0]
    segment_dy = segment_end[1] - segment_start[1]
    segment_length_squared = segment_dx * segment_dx + segment_dy * segment_dy
    if segment_length_squared == 0:
        return (
            (point[0] - segment_start[0]) ** 2
            + (point[1] - segment_start[1]) ** 2
        ) ** 0.5

    projection = (
        ((point[0] - segment_start[0]) * segment_dx)
        + ((point[1] - segment_start[1]) * segment_dy)
    ) / segment_length_squared
    projection = max(0.0, min(1.0, projection))
    closest_point = (
        segment_start[0] + projection * segment_dx,
        segment_start[1] + projection * segment_dy,
    )
    return (
        (point[0] - closest_point[0]) ** 2
        + (point[1] - closest_point[1]) ** 2
    ) ** 0.5


def did_cross_line_with_tolerance(
    previous_point,
    current_point,
    line_start,
    line_end,
    tolerance_pixels,
):
    if did_cross_line(previous_point, current_point, line_start, line_end):
        return True

    previous_distance = signed_distance_to_line(previous_point, line_start, line_end)
    current_distance = signed_distance_to_line(current_point, line_start, line_end)
    near_line = (
        abs(previous_distance) <= tolerance_pixels
        or abs(current_distance) <= tolerance_pixels
        or distance_point_to_segment(line_start, previous_point, current_point) <= tolerance_pixels
        or distance_point_to_segment(line_end, previous_point, current_point) <= tolerance_pixels
    )
    if not near_line:
        return False

    previous_sign = sign_with_dead_zone(previous_distance, tolerance_pixels)
    current_sign = sign_with_dead_zone(current_distance, tolerance_pixels)
    return previous_sign != current_sign and (
        previous_sign != 0 or current_sign != 0
    )


def sign_with_dead_zone(value, tolerance_pixels):
    if abs(value) <= tolerance_pixels:
        return 0
    return -1 if value < 0 else 1


def build_empty_class_counts():
    return {
        "bicycle": 0,
        "motorcycle": 0,
        "car": 0,
        "bus": 0,
        "truck": 0,
    }


def build_empty_direction_counts():
    return {
        DIRECTION_NEGATIVE_TO_POSITIVE: build_empty_class_counts(),
        DIRECTION_POSITIVE_TO_NEGATIVE: build_empty_class_counts(),
    }


def build_empty_line_result(line_key):
    return {
        "line_key": line_key,
        "total": 0,
        "counts": build_empty_class_counts(),
        "direction_counts": build_empty_direction_counts(),
    }


def build_empty_counts(line_keys=None):
    line_keys = tuple(line_keys or DEFAULT_LINE_KEYS)
    return {
        "total": 0,
        "counts": build_empty_class_counts(),
        "direction_counts": build_empty_direction_counts(),
        "line_results": {
            line_key: build_empty_line_result(line_key)
            for line_key in line_keys
        },
        "counted_track_ids": {line_key: set() for line_key in line_keys},
        "processed_frames": 0,
        "events": [],
        "event_sequence": 0,
    }


def track_vehicles(
    video_source,
    line_points,
    settings=None,
    track_label_mode="off",
    annotated_video_options=None,
    progress_callback=None,
    should_cancel=None,
):
    settings = normalize_settings(settings)
    model, error_message = load_model(settings["model_size"])
    if error_message:
        return None, None, build_processing_status(
            PROCESSING_STATUS_ERROR,
            error_message,
        )

    reset_tracker_state(model)
    target_class_ids = get_target_class_ids(model, settings["enabled_classes"])
    line_definitions = build_line_definitions(line_points)
    if not line_definitions:
        return None, None, build_processing_status(
            PROCESSING_STATUS_ERROR,
            "Define at least one count line before starting counting.",
        )
    playable_input = get_playable_input(video_source)
    is_live_source = is_live_video_source(video_source)
    prioritize_low_latency = (
        is_live_source and settings["prioritize_low_latency_live_streams"]
    )

    counts = build_empty_counts(line_keys=line_definitions.keys())
    last_positions = {}
    latest_frame = None
    annotated_video_session = build_annotated_video_session(
        annotated_video_options,
        line_points_by_key=line_points,
    )

    try:
        capture, error_message = open_video_capture(
            playable_input,
            is_live=is_live_source,
            prioritize_low_latency=prioritize_low_latency,
        )
        if error_message:
            if is_direct_stream_url(playable_input):
                return None, None, build_processing_status(
                    PROCESSING_STATUS_ERROR,
                    "The video stream could not be opened for tracking.",
                )
            return None, None, build_processing_status(
                PROCESSING_STATUS_ERROR,
                "The selected video could not be opened for tracking.",
            )

        if prioritize_low_latency:
            latest_frame, counts, processing_status = process_live_stream_latest_frame(
                capture=capture,
                playable_input=playable_input,
                prioritize_low_latency=prioritize_low_latency,
                model=model,
                target_class_ids=target_class_ids,
                line_definitions=line_definitions,
                counts=counts,
                last_positions=last_positions,
                settings=settings,
                track_label_mode=track_label_mode,
                annotated_video_session=annotated_video_session,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
            )
            finalize_annotated_video_session(annotated_video_session, counts)
            return latest_frame, counts, processing_status

        latest_frame, counts, processing_status = process_sequential_video(
            capture=capture,
            model=model,
            target_class_ids=target_class_ids,
            line_definitions=line_definitions,
            counts=counts,
            last_positions=last_positions,
            settings=settings,
            track_label_mode=track_label_mode,
            annotated_video_session=annotated_video_session,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        finalize_annotated_video_session(annotated_video_session, counts)
        return latest_frame, counts, finalize_processing_status(
            processing_status=processing_status,
            latest_frame=latest_frame,
            playable_input=playable_input,
            is_live_source=is_live_source,
        )
    except Exception as exc:
        finalize_annotated_video_session(annotated_video_session, counts)
        return None, None, build_processing_status(
            PROCESSING_STATUS_ERROR,
            f"Video processing failed: {exc}",
        )


def build_processing_status(code, message=None):
    return {"code": code, "message": message}


def get_playable_input(video_source):
    if isinstance(video_source, VideoSource):
        return video_source.playable_input
    return video_source


def is_live_video_source(video_source):
    if isinstance(video_source, VideoSource):
        return bool(video_source.is_live)
    return False


def process_sequential_video(
    capture,
    model,
    target_class_ids,
    line_definitions,
    counts,
    last_positions,
    settings,
    track_label_mode,
    annotated_video_session,
    progress_callback,
    should_cancel,
):
    import cv2

    try:
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if annotated_video_session and annotated_video_session.get("enabled"):
            source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if source_fps > 0:
                annotated_video_session["fps"] = source_fps
        estimated_processed_frames = (
            max(1, (total_frames + settings["frame_skip"] - 1) // settings["frame_skip"])
            if total_frames
            else 0
        )
        source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_number = 0

        while True:
            if should_cancel and should_cancel():
                return latest_frame_from_counts(counts), counts, build_processing_status(
                    PROCESSING_STATUS_CANCELLED
                )

            success, frame = capture.read()
            if not success:
                break

            frame_number += 1
            if (frame_number - 1) % settings["frame_skip"] != 0:
                continue

            latest_frame = process_frame_for_counting(
                frame=frame,
                model=model,
                target_class_ids=target_class_ids,
                line_definitions=line_definitions,
                counts=counts,
                last_positions=last_positions,
                settings=settings,
                track_label_mode=track_label_mode,
                annotated_video_session=annotated_video_session,
                frame_index=frame_number,
                source_fps=source_fps,
            )
            if isinstance(latest_frame, dict):
                return None, counts, latest_frame

            counts["_latest_frame"] = latest_frame
            if progress_callback and should_send_progress_update(
                counts["processed_frames"], estimated_processed_frames
            ):
                progress_callback(
                    counts["processed_frames"],
                    estimated_processed_frames,
                    latest_frame,
                    build_progress_snapshot(counts),
                )
    finally:
        capture.release()

    return latest_frame_from_counts(counts), counts, build_processing_status(
        PROCESSING_STATUS_COMPLETED
    )


def process_live_stream_latest_frame(
    capture,
    playable_input,
    prioritize_low_latency,
    model,
    target_class_ids,
    line_definitions,
    counts,
    last_positions,
    settings,
    track_label_mode,
    annotated_video_session,
    progress_callback,
    should_cancel,
):
    import cv2

    frame_buffer = LiveFrameBuffer(
        capture=capture,
        playable_input=playable_input,
        prioritize_low_latency=prioritize_low_latency,
    )
    frame_buffer.start()
    last_progress_time = 0.0
    fetched_frame_count = 0
    last_stream_message = None
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if annotated_video_session and annotated_video_session.get("enabled"):
        if source_fps > 0:
            annotated_video_session["fps"] = source_fps

    try:
        while True:
            if should_cancel and should_cancel():
                return latest_frame_from_counts(counts), counts, build_processing_status(
                    PROCESSING_STATUS_CANCELLED
                )

            frame = frame_buffer.get_latest_frame(wait_timeout=0.25)
            if frame is None:
                stream_message = frame_buffer.consume_status_message()
                if stream_message:
                    last_stream_message = stream_message
                if frame_buffer.has_ended():
                    break
                if stream_message and progress_callback and should_send_live_progress_update(
                    counts["processed_frames"], last_progress_time, force=True
                ):
                    last_progress_time = time.monotonic()
                    progress_callback(
                        counts["processed_frames"],
                        0,
                        latest_frame_from_counts(counts),
                        build_progress_snapshot(counts, stream_message=stream_message),
                    )
                continue

            stream_message = frame_buffer.consume_status_message()
            if stream_message:
                last_stream_message = stream_message

            fetched_frame_count += 1
            if (fetched_frame_count - 1) % settings["frame_skip"] != 0:
                continue

            latest_frame = process_frame_for_counting(
                frame=frame,
                model=model,
                target_class_ids=target_class_ids,
                line_definitions=line_definitions,
                counts=counts,
                last_positions=last_positions,
                settings=settings,
                track_label_mode=track_label_mode,
                annotated_video_session=annotated_video_session,
                frame_index=fetched_frame_count,
                source_fps=source_fps,
            )
            if isinstance(latest_frame, dict):
                return None, counts, latest_frame

            counts["_latest_frame"] = latest_frame
            if progress_callback and should_send_live_progress_update(
                counts["processed_frames"], last_progress_time
            ):
                last_progress_time = time.monotonic()
                progress_callback(
                    counts["processed_frames"],
                    0,
                    latest_frame,
                    build_progress_snapshot(counts, stream_message=stream_message),
                )
    finally:
        frame_buffer.stop()

    latest_frame = latest_frame_from_counts(counts)
    if latest_frame is None:
        return None, counts, build_processing_status(
            PROCESSING_STATUS_ERROR,
            "The stream ended before any frames could be read.",
        )

    final_message = frame_buffer.get_terminal_message() or last_stream_message
    if not final_message:
        final_message = "The live stream ended or the network connection was interrupted."

    return latest_frame, counts, build_processing_status(
        PROCESSING_STATUS_STREAM_STOPPED,
        final_message,
    )


def process_frame_for_counting(
    frame,
    model,
    target_class_ids,
    line_definitions,
    counts,
    last_positions,
    settings,
    track_label_mode,
    annotated_video_session,
    frame_index,
    source_fps,
):
    counts["processed_frames"] += 1

    try:
        results = model.track(
            frame,
            persist=True,
            classes=target_class_ids,
            tracker=get_tracker_config(settings),
            conf=settings["confidence_threshold"],
            verbose=False,
        )
    except Exception as exc:
        return build_processing_status(
            PROCESSING_STATUS_ERROR,
            f"Tracking failed while running inference: {exc}",
        )

    if not results:
        return frame.copy()

    result = results[0]
    latest_frame = render_tracking_preview_frame(
        result=result,
        model=model,
        track_label_mode=track_label_mode,
    )
    update_counts_from_result(
        result=result,
        model=model,
        last_positions=last_positions,
        line_definitions=line_definitions,
        counts=counts,
        frame_index=frame_index,
        source_fps=source_fps,
    )
    write_annotated_video_frame(
        annotated_video_session=annotated_video_session,
        source_frame=latest_frame,
        counts=counts,
    )
    return latest_frame


def get_tracker_config(settings):
    if settings.get("motorcycle_tracking") and MOTORCYCLE_TRACKER_CONFIG.exists():
        return str(MOTORCYCLE_TRACKER_CONFIG)
    return TRACKER_CONFIG


def finalize_processing_status(processing_status, latest_frame, playable_input, is_live_source):
    status_code = processing_status["code"]
    if status_code != PROCESSING_STATUS_COMPLETED:
        return processing_status

    if latest_frame is None:
        if is_direct_stream_url(playable_input) or is_remote_video_source(playable_input):
            return build_processing_status(
                PROCESSING_STATUS_ERROR,
                "The stream ended before any frames could be read.",
            )
        return build_processing_status(
            PROCESSING_STATUS_ERROR,
            "The video could not be read frame by frame.",
        )

    if is_live_source:
        return build_processing_status(
            PROCESSING_STATUS_STREAM_STOPPED,
            "The live stream ended or the network connection was interrupted.",
        )

    return processing_status


def latest_frame_from_counts(counts):
    return counts.get("_latest_frame")


def reset_tracker_state(model):
    predictor = getattr(model, "predictor", None)
    trackers = getattr(predictor, "trackers", None)
    if not trackers:
        return

    for tracker in trackers:
        reset = getattr(tracker, "reset", None)
        if callable(reset):
            reset()


def update_counts_from_result(
    result,
    model,
    last_positions,
    line_definitions,
    counts,
    frame_index,
    source_fps,
):
    if result.boxes is None or result.boxes.id is None or result.boxes.cls is None:
        return

    track_ids = result.boxes.id.int().tolist()
    class_ids = result.boxes.cls.int().tolist()
    boxes = result.boxes.xyxy.tolist()

    for track_id, class_id, box in zip(track_ids, class_ids, boxes):
        current_points = build_track_points(box)
        previous_points = last_positions.get(track_id)
        class_name = model.names[int(class_id)]

        if previous_points:
            for line_key, line_definition in line_definitions.items():
                counted_track_ids = counts["counted_track_ids"].setdefault(line_key, set())
                if track_id in counted_track_ids:
                    continue

                line_start = line_definition["start"]
                line_end = line_definition["end"]
                previous_point, current_point = get_crossing_points_for_class(
                    class_name=class_name,
                    previous_points=previous_points,
                    current_points=current_points,
                    line_start=line_start,
                    line_end=line_end,
                )
                if previous_point is None or current_point is None:
                    continue

                if not did_cross_for_class(
                    class_name,
                    previous_point,
                    current_point,
                    line_start,
                    line_end,
                ):
                    continue

                direction = get_crossing_direction_for_class(
                    class_name, previous_point, current_point, line_start, line_end
                )
                counted_track_ids.add(track_id)
                increment_result_counts(counts, class_name, direction)
                increment_result_counts(
                    counts["line_results"][line_key],
                    class_name,
                    direction,
                )
                append_count_event(
                    counts=counts,
                    line_key=line_key,
                    direction=direction,
                    class_name=class_name,
                    track_id=track_id,
                    frame_index=frame_index,
                    source_fps=source_fps,
                )

        last_positions[track_id] = current_points


def build_track_points(box):
    return {
        "center": (
            (box[0] + box[2]) / 2,
            (box[1] + box[3]) / 2,
        ),
        "bottom_center": (
            (box[0] + box[2]) / 2,
            box[3],
        ),
    }


def get_crossing_points_for_class(
    class_name,
    previous_points,
    current_points,
    line_start,
    line_end,
):
    if class_name != MOTORCYCLE_CLASS_NAME:
        return previous_points.get("center"), current_points.get("center")

    for point_key in ("center", "bottom_center"):
        previous_point = previous_points.get(point_key)
        current_point = current_points.get(point_key)
        if previous_point is None or current_point is None:
            continue
        if did_cross_for_class(class_name, previous_point, current_point, line_start, line_end):
            return previous_point, current_point

    return previous_points.get("center"), current_points.get("center")


def did_cross_for_class(class_name, previous_point, current_point, line_start, line_end):
    if class_name == MOTORCYCLE_CLASS_NAME:
        return did_cross_line_with_tolerance(
            previous_point,
            current_point,
            line_start,
            line_end,
            MOTORCYCLE_CROSSING_TOLERANCE_PIXELS,
        )
    return did_cross_line(previous_point, current_point, line_start, line_end)


def get_crossing_direction_for_class(
    class_name,
    previous_point,
    current_point,
    line_start,
    line_end,
):
    direction = get_crossing_direction(previous_point, current_point, line_start, line_end)
    if direction != "unknown" or class_name != MOTORCYCLE_CLASS_NAME:
        return direction

    previous_distance = signed_distance_to_line(previous_point, line_start, line_end)
    current_distance = signed_distance_to_line(current_point, line_start, line_end)
    if current_distance >= previous_distance:
        return DIRECTION_NEGATIVE_TO_POSITIVE
    return DIRECTION_POSITIVE_TO_NEGATIVE


def build_line_definitions(line_points_by_key):
    line_definitions = {}
    for line_key, line_points in (line_points_by_key or {}).items():
        if not line_points:
            continue
        line_definitions[line_key] = {
            "start": (line_points[0].x(), line_points[0].y()),
            "end": (line_points[1].x(), line_points[1].y()),
        }
    return line_definitions


def increment_result_counts(result_bucket, class_name, direction):
    result_bucket["counts"][class_name] = result_bucket["counts"].get(class_name, 0) + 1
    if direction in result_bucket["direction_counts"]:
        direction_counts = result_bucket["direction_counts"][direction]
        direction_counts[class_name] = direction_counts.get(class_name, 0) + 1
    result_bucket["total"] += 1


def append_count_event(
    counts,
    line_key,
    direction,
    class_name,
    track_id,
    frame_index,
    source_fps,
):
    counts["event_sequence"] += 1
    elapsed_seconds = (
        max(0.0, float(frame_index - 1) / float(source_fps))
        if source_fps and source_fps > 0
        else None
    )
    counts["events"].append(
        {
            "event_id": f"EVT-{counts['event_sequence']:06d}",
            "line_id": line_key,
            "direction": direction,
            "vehicle_class": class_name,
            "track_id": track_id,
            "frame_index": frame_index,
            "elapsed_seconds": elapsed_seconds,
            "event_timecode": format_event_timecode(elapsed_seconds),
        }
    )


def format_event_timecode(elapsed_seconds):
    if elapsed_seconds is None:
        return ""

    total_milliseconds = max(0, round(elapsed_seconds * 1000))
    hours = total_milliseconds // 3600000
    remaining = total_milliseconds % 3600000
    minutes = remaining // 60000
    remaining %= 60000
    seconds = remaining // 1000
    milliseconds = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def should_send_progress_update(processed_frames, total_frames):
    if processed_frames == 1:
        return True
    if processed_frames % 10 == 0:
        return True
    if total_frames and processed_frames == total_frames:
        return True
    return False


def should_send_live_progress_update(processed_frames, last_progress_time, force=False):
    if force:
        return True
    if processed_frames == 1:
        return True
    return (time.monotonic() - last_progress_time) >= LIVE_PROGRESS_INTERVAL_SECONDS


def build_progress_snapshot(counts, stream_message=None):
    return {
        "total": counts["total"],
        "counts": dict(counts["counts"]),
        "direction_counts": {
            direction: dict(direction_counts)
            for direction, direction_counts in counts["direction_counts"].items()
        },
        "line_results": {
            line_key: {
                "line_key": line_result["line_key"],
                "total": line_result["total"],
                "counts": dict(line_result["counts"]),
                "direction_counts": {
                    direction: dict(direction_counts)
                    for direction, direction_counts in line_result["direction_counts"].items()
                },
            }
            for line_key, line_result in counts["line_results"].items()
        },
        "processed_frames": counts["processed_frames"],
        "stream_message": stream_message,
    }


def build_annotated_video_session(annotated_video_options, line_points_by_key):
    options = annotated_video_options or {}
    return {
        "enabled": bool(options.get("enabled")),
        "output_path": options.get("output_path"),
        "fps": options.get("fps") or 20.0,
        "line_points_by_key": {
            line_key: line_points
            for line_key, line_points in (line_points_by_key or {}).items()
            if line_points is not None
        },
        "direction_labels_by_line": options.get("direction_labels_by_line") or {},
        "line_colors": options.get("line_colors") or {},
        "line_short_names": options.get("line_short_names") or {},
        "writer": None,
        "started": False,
        "failed": False,
        "failure_message": None,
        "completed_message": None,
    }


def write_annotated_video_frame(annotated_video_session, source_frame, counts):
    if not annotated_video_session or not annotated_video_session.get("enabled"):
        return
    if annotated_video_session.get("failed"):
        return
    writer = annotated_video_session.get("writer")
    if writer is None:
        writer, error_message = build_video_writer(
            annotated_video_session.get("output_path"),
            (source_frame.shape[1], source_frame.shape[0]),
            annotated_video_session.get("fps"),
        )
        if error_message:
            annotated_video_session["failed"] = True
            annotated_video_session["failure_message"] = error_message
            return
        annotated_video_session["writer"] = writer
        annotated_video_session["started"] = True

    try:
        review_frame = draw_review_overlay(
            source_frame,
            line_points_by_key=annotated_video_session.get("line_points_by_key"),
            direction_labels_by_line=annotated_video_session.get("direction_labels_by_line"),
            line_colors=annotated_video_session.get("line_colors"),
            line_short_names=annotated_video_session.get("line_short_names"),
            counts_snapshot=build_progress_snapshot(counts),
        )
        annotated_video_session["writer"].write(review_frame)
    except Exception as exc:
        annotated_video_session["failed"] = True
        annotated_video_session["failure_message"] = f"Annotated video save failed: {exc}"
        try:
            annotated_video_session["writer"].release()
        except Exception:
            pass
        annotated_video_session["writer"] = None


def finalize_annotated_video_session(annotated_video_session, counts):
    if not annotated_video_session:
        return
    writer = annotated_video_session.get("writer")
    if writer is not None:
        try:
            writer.release()
        except Exception:
            pass
        annotated_video_session["writer"] = None

    if not annotated_video_session.get("enabled"):
        return

    counts["annotated_video"] = {
        "enabled": True,
        "output_path": annotated_video_session.get("output_path"),
        "started": annotated_video_session.get("started", False),
        "failed": annotated_video_session.get("failed", False),
        "message": annotated_video_session.get("failure_message")
        or (
            f"Annotated video saved to {annotated_video_session.get('output_path')}"
            if annotated_video_session.get("started")
            else "Annotated video was enabled but no frames were written."
        ),
    }


class LiveFrameBuffer:
    def __init__(self, capture, playable_input, prioritize_low_latency):
        self.capture = capture
        self.playable_input = playable_input
        self.prioritize_low_latency = prioritize_low_latency
        self.lock = threading.Lock()
        self.thread = None
        self.stop_requested = False
        self.latest_frame = None
        self.frame_sequence = 0
        self.last_delivered_sequence = 0
        self.stream_ended = False
        self.status_message = None
        self.terminal_message = None
        self.failure_started_at = None
        self.reopen_attempts = 0

    def start(self):
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_requested = True
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        self.capture.release()

    def has_ended(self):
        with self.lock:
            return self.stream_ended

    def consume_status_message(self):
        with self.lock:
            message = self.status_message
            self.status_message = None
            return message

    def get_terminal_message(self):
        with self.lock:
            return self.terminal_message

    def get_latest_frame(self, wait_timeout):
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.frame_sequence > self.last_delivered_sequence:
                    self.last_delivered_sequence = self.frame_sequence
                    return self.latest_frame.copy()
                if self.stream_ended:
                    return None
            time.sleep(0.01)
        return None

    def _reader_loop(self):
        while not self.stop_requested:
            success, frame = self.capture.read()
            if not success or frame is None:
                if self._handle_read_failure():
                    continue
                return
            with self.lock:
                self.latest_frame = frame
                self.frame_sequence += 1
                self.failure_started_at = None
                self.status_message = None

    def _handle_read_failure(self):
        now = time.monotonic()
        with self.lock:
            if self.failure_started_at is None:
                self.failure_started_at = now
            self.status_message = "Temporary stream read failure. Retrying live stream..."
            failure_duration = now - self.failure_started_at

        if failure_duration >= LIVE_READ_FAILURE_REOPEN_THRESHOLD:
            if self._attempt_reopen():
                with self.lock:
                    self.failure_started_at = None
                    self.status_message = "Live stream reconnected. Resuming counting..."
                return True

        if failure_duration < LIVE_READ_FAILURE_GRACE_SECONDS and not self.stop_requested:
            time.sleep(LIVE_READ_RETRY_DELAY_SECONDS)
            return True

        with self.lock:
            self.stream_ended = True
            if self.reopen_attempts > 0:
                self.terminal_message = "Live stream disconnected after retry attempts. Partial results were kept."
            else:
                self.terminal_message = "Live stream ended after repeated read failures. Partial results were kept."
        return False

    def _attempt_reopen(self):
        with self.lock:
            if self.reopen_attempts >= LIVE_MAX_REOPEN_ATTEMPTS:
                return False
            self.reopen_attempts += 1
            self.status_message = "Retrying live stream connection..."

        try:
            self.capture.release()
        except Exception:
            pass

        capture, error_message = open_video_capture(
            self.playable_input,
            is_live=True,
            prioritize_low_latency=self.prioritize_low_latency,
        )
        if error_message:
            return False

        self.capture = capture
        return True
