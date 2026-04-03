from .detection import get_target_class_ids, load_model, normalize_settings


TRACKER_CONFIG = "bytetrack.yaml"
DIRECTION_NEGATIVE_TO_POSITIVE = "negative_to_positive"
DIRECTION_POSITIVE_TO_NEGATIVE = "positive_to_negative"


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


def build_empty_counts():
    return {
        "total": 0,
        "counts": {
            "bicycle": 0,
            "motorcycle": 0,
            "car": 0,
            "bus": 0,
            "truck": 0,
        },
        "direction_counts": {
            DIRECTION_NEGATIVE_TO_POSITIVE: {
                "bicycle": 0,
                "motorcycle": 0,
                "car": 0,
                "bus": 0,
                "truck": 0,
            },
            DIRECTION_POSITIVE_TO_NEGATIVE: {
                "bicycle": 0,
                "motorcycle": 0,
                "car": 0,
                "bus": 0,
                "truck": 0,
            },
        },
        "counted_track_ids": set(),
        "processed_frames": 0,
    }


def track_vehicles(
    video_path,
    line_points,
    settings=None,
    progress_callback=None,
    should_cancel=None,
):
    settings = normalize_settings(settings)
    model, error_message = load_model(settings["model_size"])
    if error_message:
        return None, None, error_message

    reset_tracker_state(model)
    target_class_ids = get_target_class_ids(model, settings["enabled_classes"])
    line_start = (line_points[0].x(), line_points[0].y())
    line_end = (line_points[1].x(), line_points[1].y())

    counts = build_empty_counts()
    last_positions = {}
    latest_frame = None

    try:
        import cv2

        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            capture.release()
            return None, None, "The selected video could not be opened for tracking."

        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        estimated_processed_frames = max(1, (total_frames + settings["frame_skip"] - 1) // settings["frame_skip"]) if total_frames else 0
        frame_number = 0

        while True:
            if should_cancel and should_cancel():
                capture.release()
                return latest_frame, counts, "cancelled"

            success, frame = capture.read()
            if not success:
                break

            frame_number += 1
            if (frame_number - 1) % settings["frame_skip"] != 0:
                continue

            counts["processed_frames"] += 1

            try:
                results = model.track(
                    frame,
                    persist=True,
                    classes=target_class_ids,
                    tracker=TRACKER_CONFIG,
                    conf=settings["confidence_threshold"],
                    verbose=False,
                )
            except Exception as exc:
                capture.release()
                return None, None, f"Tracking failed while running inference: {exc}"

            if not results:
                latest_frame = frame.copy()
                continue

            result = results[0]
            latest_frame = result.plot()
            update_counts_from_result(
                result=result,
                model=model,
                last_positions=last_positions,
                line_start=line_start,
                line_end=line_end,
                counts=counts,
            )

            if progress_callback and should_send_progress_update(
                counts["processed_frames"], estimated_processed_frames
            ):
                progress_callback(
                    counts["processed_frames"],
                    estimated_processed_frames,
                    latest_frame,
                    build_progress_snapshot(counts),
                )

        capture.release()
    except Exception as exc:
        return None, None, f"Video processing failed: {exc}"

    if latest_frame is None:
        return None, None, "The video could not be read frame by frame."

    return latest_frame, counts, None


def reset_tracker_state(model):
    predictor = getattr(model, "predictor", None)
    trackers = getattr(predictor, "trackers", None)
    if not trackers:
        return

    for tracker in trackers:
        reset = getattr(tracker, "reset", None)
        if callable(reset):
            reset()


def update_counts_from_result(result, model, last_positions, line_start, line_end, counts):
    if result.boxes is None or result.boxes.id is None or result.boxes.cls is None:
        return

    track_ids = result.boxes.id.int().tolist()
    class_ids = result.boxes.cls.int().tolist()
    boxes = result.boxes.xyxy.tolist()

    for track_id, class_id, box in zip(track_ids, class_ids, boxes):
        center_point = (
            (box[0] + box[2]) / 2,
            (box[1] + box[3]) / 2,
        )
        previous_point = last_positions.get(track_id)
        class_name = model.names[int(class_id)]

        if previous_point and track_id not in counts["counted_track_ids"]:
            if did_cross_line(previous_point, center_point, line_start, line_end):
                direction = get_crossing_direction(
                    previous_point, center_point, line_start, line_end
                )
                counts["counted_track_ids"].add(track_id)
                counts["counts"][class_name] = counts["counts"].get(class_name, 0) + 1
                if direction in counts["direction_counts"]:
                    direction_counts = counts["direction_counts"][direction]
                    direction_counts[class_name] = direction_counts.get(class_name, 0) + 1
                counts["total"] += 1

        last_positions[track_id] = center_point


def should_send_progress_update(processed_frames, total_frames):
    if processed_frames == 1:
        return True
    if processed_frames % 10 == 0:
        return True
    if total_frames and processed_frames == total_frames:
        return True
    return False


def build_progress_snapshot(counts):
    return {
        "total": counts["total"],
        "counts": dict(counts["counts"]),
        "direction_counts": {
            direction: dict(direction_counts)
            for direction, direction_counts in counts["direction_counts"].items()
        },
        "processed_frames": counts["processed_frames"],
    }
