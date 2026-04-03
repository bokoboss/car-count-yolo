ROAD_USER_CLASS_NAMES = ("bicycle", "car", "motorcycle", "bus", "truck")
MODEL_NAME_BY_SIZE = {
    "nano": "yolo11n.pt",
    "small": "yolo11s.pt",
    "medium": "yolo11m.pt",
}

_loaded_models = {}


def load_model(model_size="nano"):
    model_size = normalize_model_size(model_size)

    if model_size in _loaded_models:
        return _loaded_models[model_size], None

    try:
        from ultralytics import YOLO

        model = YOLO(MODEL_NAME_BY_SIZE[model_size])
        _loaded_models[model_size] = model
    except Exception as exc:
        return None, f"Could not load the YOLO model: {exc}"

    return model, None


def get_target_class_ids(model, enabled_classes=None):
    allowed_classes = set(enabled_classes or ROAD_USER_CLASS_NAMES)
    return [
        class_id
        for class_id, class_name in model.names.items()
        if class_name in allowed_classes
    ]


def detect_vehicles(frame, settings=None):
    settings = normalize_settings(settings)
    model, error_message = load_model(settings["model_size"])
    if error_message:
        return None, None, error_message

    target_class_ids = get_target_class_ids(model, settings["enabled_classes"])

    try:
        results = model.predict(
            frame,
            classes=target_class_ids,
            conf=settings["confidence_threshold"],
            verbose=False,
        )
    except Exception as exc:
        return None, None, f"Detection failed while running inference: {exc}"

    if not results:
        return frame.copy(), {"total": 0, "counts": {}}, None

    result = results[0]
    annotated_frame = result.plot()
    counts_by_class = {}

    if result.boxes is not None and result.boxes.cls is not None:
        for class_id in result.boxes.cls.tolist():
            class_name = model.names[int(class_id)]
            counts_by_class[class_name] = counts_by_class.get(class_name, 0) + 1

    summary = {
        "total": sum(counts_by_class.values()),
        "counts": counts_by_class,
    }
    return annotated_frame, summary, None


def normalize_settings(settings):
    settings = settings or {}
    return {
        "confidence_threshold": normalize_confidence_threshold(
            settings.get("confidence_threshold", 0.30)
        ),
        "frame_skip": normalize_frame_skip(settings.get("frame_skip", 1)),
        "model_size": normalize_model_size(settings.get("model_size", "nano")),
        "enabled_classes": normalize_enabled_classes(
            settings.get("enabled_classes", ROAD_USER_CLASS_NAMES)
        ),
    }


def normalize_confidence_threshold(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.30
    return max(0.0, min(1.0, value))


def normalize_frame_skip(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def normalize_model_size(value):
    if value in MODEL_NAME_BY_SIZE:
        return value
    return "nano"


def normalize_enabled_classes(value):
    if not value:
        return list(ROAD_USER_CLASS_NAMES)

    normalized_classes = [class_name for class_name in value if class_name in ROAD_USER_CLASS_NAMES]
    if not normalized_classes:
        return list(ROAD_USER_CLASS_NAMES)
    return normalized_classes
