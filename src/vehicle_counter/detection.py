from . import config


ROAD_USER_CLASS_NAMES = config.SUPPORTED_COUNT_CLASSES
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
        inference_options = build_inference_options(settings)
        results = model.predict(
            frame,
            classes=target_class_ids,
            conf=settings["confidence_threshold"],
            verbose=False,
            **inference_options,
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
    counting_mode = config.normalize_counting_mode(
        settings.get("counting_mode", config.DEFAULT_COUNTING_MODE)
    )
    return {
        "counting_mode": counting_mode,
        "confidence_threshold": normalize_confidence_threshold(
            settings.get("confidence_threshold", 0.30)
        ),
        "frame_skip": normalize_frame_skip(settings.get("frame_skip", 1)),
        "model_size": normalize_model_size(settings.get("model_size", "nano")),
        "enabled_classes": normalize_enabled_classes(
            settings.get("enabled_classes"),
            counting_mode=counting_mode,
        ),
        "prioritize_low_latency_live_streams": normalize_boolean(
            settings.get("prioritize_low_latency_live_streams", True)
        ),
        "motorcycle_tracking": normalize_boolean(settings.get("motorcycle_tracking", False)),
        "imgsz": normalize_image_size(settings.get("imgsz", config.DEFAULT_IMAGE_SIZE)),
        "device": normalize_device(settings.get("device", config.DEFAULT_DEVICE)),
        "half": normalize_boolean(settings.get("half", config.DEFAULT_HALF_PRECISION)),
        "tracker_config": normalize_tracker_config(settings.get("tracker_config")),
        "preview_render_mode": normalize_preview_render_mode(
            settings.get("preview_render_mode", config.DEFAULT_PREVIEW_RENDER_MODE)
        ),
    }


def normalize_confidence_threshold(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.30
    return max(0.0, min(1.0, value))


def build_inference_options(settings):
    options = {
        "imgsz": settings["imgsz"],
        "half": settings["half"],
    }
    if settings.get("device") is not None:
        options["device"] = settings["device"]
    return options


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


def normalize_enabled_classes(value, counting_mode=None):
    default_classes = config.get_default_enabled_classes_for_mode(
        config.normalize_counting_mode(counting_mode)
    )
    if not value:
        return list(default_classes)

    allowed_classes = set(default_classes)
    normalized_classes = [
        class_name
        for class_name in value
        if class_name in ROAD_USER_CLASS_NAMES and class_name in allowed_classes
    ]
    if not normalized_classes:
        return list(default_classes)
    return normalized_classes


def normalize_image_size(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return config.DEFAULT_IMAGE_SIZE
    return max(320, min(1280, value))


def normalize_device(value):
    if value in (None, "", "auto"):
        return None
    return str(value).strip()


def normalize_tracker_config(value):
    if value in (None, ""):
        return None
    return str(value)


def normalize_preview_render_mode(value):
    if value == config.PREVIEW_RENDER_RAW:
        return config.PREVIEW_RENDER_RAW
    return config.PREVIEW_RENDER_ANNOTATED


def normalize_boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
